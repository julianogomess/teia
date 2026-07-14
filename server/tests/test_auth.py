"""Login com senha, refresh com rotação, logout e login com Google (mockado)."""

from sqlalchemy import select

from app.config import settings
from app.models import AuthEvent, RefreshToken, User

from .conftest import auth_headers, login


def test_login_ok(client, seed):
    res = client.post(
        "/api/auth/login",
        json={"email": "admin@teia.org.br", "password": "senha-admin-123"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"]
    assert data["user"]["role"] == "superadmin"
    assert data["user"]["org_label"] == "TeIA"
    assert "teia_refresh" in res.cookies


def test_login_senha_errada_registra_evento(client, seed, db):
    res = client.post(
        "/api/auth/login",
        json={"email": "admin@teia.org.br", "password": "errada12"},
    )
    assert res.status_code == 401
    event = db.scalar(select(AuthEvent).order_by(AuthEvent.id.desc()))
    assert event.success is False
    assert event.email == "admin@teia.org.br"


def test_login_rate_limit_por_ip(client, seed):
    for _ in range(settings.login_rate_per_minute):
        client.post("/api/auth/login", json={"email": "x@x.com", "password": "errada12"})
    res = client.post("/api/auth/login", json={"email": "x@x.com", "password": "errada12"})
    assert res.status_code == 429


def test_refresh_rotaciona_token(client, seed, db):
    client.post(
        "/api/auth/login",
        json={"email": "admin@teia.org.br", "password": "senha-admin-123"},
    )
    old_cookie = client.cookies.get("teia_refresh")
    res = client.post("/api/auth/refresh")
    assert res.status_code == 200
    assert res.json()["access_token"]
    new_cookie = client.cookies.get("teia_refresh")
    assert new_cookie != old_cookie
    # o token antigo foi revogado e não pode ser reusado
    client.cookies.set("teia_refresh", old_cookie)
    res = client.post("/api/auth/refresh")
    assert res.status_code == 401


def test_logout_revoga_sessao(client, seed, db):
    client.post(
        "/api/auth/login",
        json={"email": "admin@teia.org.br", "password": "senha-admin-123"},
    )
    assert client.post("/api/auth/logout").status_code == 200
    tokens = db.scalars(select(RefreshToken)).all()
    assert all(t.revoked_at is not None for t in tokens)


def test_usuario_bloqueado_nao_loga(client, seed, db):
    seed["member"].is_active = False
    db.commit()
    res = client.post(
        "/api/auth/login",
        json={"email": "maria@raizes.org.br", "password": "senha-maria-123"},
    )
    assert res.status_code == 401


# ------------------------------------------------------------ Google (mock)
def _mock_google(monkeypatch, email, sub="google-sub-1", verified=True):
    monkeypatch.setattr(
        "app.routers.auth._exchange_code",
        lambda code, verifier: {"id_token": "fake"},
    )
    monkeypatch.setattr(
        "app.routers.auth._verify_id_token",
        lambda id_token: {"email": email, "sub": sub, "email_verified": verified,
                          "name": "Pessoa Google"},
    )


def _start_google_flow(client, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "client-id-test")
    res = client.get("/api/auth/google/login", follow_redirects=False)
    assert res.status_code == 302
    assert "accounts.google.com" in res.headers["location"]
    # o state fica no query string do redirect e no cookie assinado
    from urllib.parse import parse_qs, urlparse
    return parse_qs(urlparse(res.headers["location"]).query)["state"][0]


def test_google_convidado_entra(client, seed, db, monkeypatch):
    state = _start_google_flow(client, monkeypatch)
    _mock_google(monkeypatch, "maria@raizes.org.br")
    res = client.get(
        f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False
    )
    assert res.status_code == 302
    assert res.headers["location"] == "/"
    assert client.cookies.get("teia_refresh")
    user = db.scalar(select(User).where(User.email == "maria@raizes.org.br"))
    assert user.google_sub == "google-sub-1"


def test_google_nao_convidado_e_barrado(client, seed, monkeypatch):
    state = _start_google_flow(client, monkeypatch)
    _mock_google(monkeypatch, "desconhecido@gmail.com")
    res = client.get(
        f"/api/auth/google/callback?code=abc&state={state}", follow_redirects=False
    )
    assert res.status_code == 302
    assert "nao_convidado" in res.headers["location"]
    assert not client.cookies.get("teia_refresh")


def test_google_state_invalido(client, seed, monkeypatch):
    _start_google_flow(client, monkeypatch)
    _mock_google(monkeypatch, "maria@raizes.org.br")
    res = client.get(
        "/api/auth/google/callback?code=abc&state=forjado", follow_redirects=False
    )
    assert res.status_code == 302
    assert "error=google" in res.headers["location"]
