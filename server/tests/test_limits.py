"""Rate limit por usuário, cotas diárias/mensais e gestão via API admin."""

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import UsageEvent

from .conftest import auth_headers, login


def _chat(client, token, text="oi"):
    return client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": text}]},
        headers=auth_headers(token),
    )


def test_rate_limit_por_usuario(client, seed, db, fake_anthropic, monkeypatch):
    monkeypatch.setattr(settings, "chat_rate_per_minute", 2)
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert _chat(client, token).status_code == 200
    assert _chat(client, token).status_code == 200
    res = _chat(client, token)
    assert res.status_code == 429
    event = db.scalar(select(UsageEvent).order_by(UsageEvent.id.desc()))
    assert event.result == "rate_limited"


def test_cota_diaria_do_usuario(client, seed, db, fake_anthropic, monkeypatch):
    seed["member"].daily_message_limit = 1
    db.commit()
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert _chat(client, token).status_code == 200
    res = _chat(client, token)
    assert res.status_code == 429
    assert "cota diária" in res.json()["detail"]
    event = db.scalar(select(UsageEvent).order_by(UsageEvent.id.desc()))
    assert event.result == "quota_exceeded"


def test_cota_mensal_de_custo_do_tenant(client, seed, db, fake_anthropic, monkeypatch):
    seed["ong"].monthly_cost_limit_usd = 0.000001
    db.commit()
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert _chat(client, token).status_code == 200  # primeira passa (custo ainda 0)
    res = _chat(client, token)
    assert res.status_code == 429
    assert "teto mensal" in res.json()["detail"]


def test_janela_do_rate_limit_reseta(client, seed, fake_anthropic, monkeypatch):
    from app.rate_limit import chat_limiter

    monkeypatch.setattr(settings, "chat_rate_per_minute", 1)
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert _chat(client, token).status_code == 200
    assert _chat(client, token).status_code == 429
    chat_limiter.reset()  # simula a passagem da janela de 60s
    assert _chat(client, token).status_code == 200


def test_admin_ajusta_cota_do_usuario(client, seed, fake_anthropic):
    admin_token = login(client, "admin@teia.org.br", "senha-admin-123")
    res = client.patch(
        f"/api/admin/users/{seed['member'].id}",
        json={"daily_message_limit": 1},
        headers=auth_headers(admin_token),
    )
    assert res.status_code == 200
    assert res.json()["daily_limit"] == 1

    member_token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert _chat(client, member_token).status_code == 200
    assert _chat(client, member_token).status_code == 429


def test_admin_convida_e_bloqueia_usuario(client, seed):
    admin_token = login(client, "admin@teia.org.br", "senha-admin-123")
    res = client.post(
        "/api/admin/users",
        json={"email": "novo@raizes.org.br", "org_slug": "ong",
              "role": "member", "password": "senha-nova-123"},
        headers=auth_headers(admin_token),
    )
    assert res.status_code == 201
    user_id = res.json()["id"]

    novo_token = login(client, "novo@raizes.org.br", "senha-nova-123")

    res = client.patch(
        f"/api/admin/users/{user_id}",
        json={"is_active": False},
        headers=auth_headers(admin_token),
    )
    assert res.status_code == 200
    # bloqueado: o token de acesso ainda existente deixa de valer
    res = client.get("/api/admin/metrics", headers=auth_headers(novo_token))
    assert res.status_code == 401
    # e não loga de novo
    res = client.post(
        "/api/auth/login",
        json={"email": "novo@raizes.org.br", "password": "senha-nova-123"},
    )
    assert res.status_code == 401


def test_corpo_grande_demais_rejeitado(client, seed):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    res = _chat(client, token, "x" * (settings.max_message_chars + 1))
    assert res.status_code in (413, 422)
