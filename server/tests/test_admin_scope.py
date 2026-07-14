"""Escopo das rotas admin por tenant.

superadmin (equipe TeIA) tem visão e gestão globais; admin (tenant) só vê e
gerencia a própria organização; member não acessa /api/admin/*.
"""

from .conftest import auth_headers, login


def _super(client):
    return login(client, "admin@teia.org.br", "senha-admin-123")


def _tenant_admin(client):
    return login(client, "gestora@raizes.org.br", "senha-gestora-123")


# ------------------------------------------------------------------- usuários
def test_member_nao_acessa_rotas_admin(client, seed):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert client.get("/api/admin/users", headers=auth_headers(token)).status_code == 403
    assert client.get("/api/admin/metrics", headers=auth_headers(token)).status_code == 403


def test_admin_do_tenant_ve_so_usuarios_da_propria_org(client, seed):
    token = _tenant_admin(client)
    res = client.get("/api/admin/users", headers=auth_headers(token))
    assert res.status_code == 200
    orgs = {u["org_slug"] for u in res.json()["users"]}
    assert orgs == {"ong"}


def test_superadmin_ve_usuarios_de_todas_as_orgs(client, seed):
    token = _super(client)
    res = client.get("/api/admin/users", headers=auth_headers(token))
    assert res.status_code == 200
    orgs = {u["org_slug"] for u in res.json()["users"]}
    assert orgs == {"teia", "ong"}


def test_admin_do_tenant_nao_convida_em_outra_org(client, seed):
    token = _tenant_admin(client)
    res = client.post(
        "/api/admin/users",
        json={"email": "intruso@teia.org.br", "org_slug": "teia", "role": "member"},
        headers=auth_headers(token),
    )
    assert res.status_code == 403


def test_admin_do_tenant_convida_na_propria_org(client, seed):
    token = _tenant_admin(client)
    res = client.post(
        "/api/admin/users",
        json={"email": "novo@raizes.org.br", "org_slug": "ong", "role": "member",
              "password": "senha-nova-123"},
        headers=auth_headers(token),
    )
    assert res.status_code == 201
    assert res.json()["org_slug"] == "ong"


def test_ninguem_alem_do_superadmin_cria_superadmin(client, seed):
    token = _tenant_admin(client)
    res = client.post(
        "/api/admin/users",
        json={"email": "novo@raizes.org.br", "org_slug": "ong", "role": "superadmin"},
        headers=auth_headers(token),
    )
    assert res.status_code == 403


def test_admin_do_tenant_nao_edita_usuario_de_outra_org(client, seed):
    token = _tenant_admin(client)
    res = client.patch(
        f"/api/admin/users/{seed['admin'].id}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    # 404 (e não 403) para não revelar que o id existe
    assert res.status_code == 404


def test_admin_do_tenant_nao_promove_a_superadmin(client, seed):
    token = _tenant_admin(client)
    res = client.patch(
        f"/api/admin/users/{seed['member'].id}",
        json={"role": "superadmin"},
        headers=auth_headers(token),
    )
    assert res.status_code == 403


def test_admin_do_mesmo_tenant_nao_altera_superadmin(client, seed, db):
    # um admin (tenant) da própria TeIA não pode mexer na conta superadmin
    super_token = _super(client)
    res = client.post(
        "/api/admin/users",
        json={"email": "gestor@teia.org.br", "org_slug": "teia", "role": "admin",
              "password": "senha-gestor-123"},
        headers=auth_headers(super_token),
    )
    assert res.status_code == 201
    token = login(client, "gestor@teia.org.br", "senha-gestor-123")
    res = client.patch(
        f"/api/admin/users/{seed['admin'].id}",
        json={"is_active": False},
        headers=auth_headers(token),
    )
    assert res.status_code == 403


def test_superadmin_edita_usuario_de_qualquer_org(client, seed):
    token = _super(client)
    res = client.patch(
        f"/api/admin/users/{seed['member'].id}",
        json={"daily_message_limit": 5},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    assert res.json()["daily_limit"] == 5


# -------------------------------------------------------------- organizações
def test_admin_do_tenant_ve_so_a_propria_org(client, seed):
    token = _tenant_admin(client)
    res = client.get("/api/admin/organizations", headers=auth_headers(token))
    assert res.status_code == 200
    slugs = [o["slug"] for o in res.json()["organizations"]]
    assert slugs == ["ong"]


def test_admin_do_tenant_nao_edita_cotas_da_org(client, seed):
    token = _tenant_admin(client)
    res = client.patch(
        "/api/admin/organizations/ong",
        json={"monthly_cost_limit_usd": 9999},
        headers=auth_headers(token),
    )
    assert res.status_code == 403


def test_superadmin_edita_cotas_de_qualquer_org(client, seed):
    token = _super(client)
    res = client.patch(
        "/api/admin/organizations/ong",
        json={"monthly_message_limit": 123},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    assert res.json()["monthly_message_limit"] == 123


# ------------------------------------------------------------------- métricas
def _chat(client, token):
    return client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "oi"}]},
        headers=auth_headers(token),
    )


def test_metricas_escopadas_ao_tenant(client, seed, fake_anthropic):
    super_token = _super(client)
    maria_token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert _chat(client, super_token).status_code == 200  # uso da TeIA
    assert _chat(client, maria_token).status_code == 200  # uso da ONG

    # superadmin: visão global
    res = client.get("/api/admin/metrics", headers=auth_headers(super_token))
    assert res.status_code == 200
    m = res.json()
    assert m["cards"]["messages_today"] == 2
    assert {o["slug"] for o in m["per_org"]} == {"teia", "ong"}

    # admin do tenant: só a própria organização
    res = client.get("/api/admin/metrics", headers=auth_headers(_tenant_admin(client)))
    assert res.status_code == 200
    m = res.json()
    assert m["cards"]["messages_today"] == 1
    assert [o["slug"] for o in m["per_org"]] == ["ong"]
    assert {u["email"] for u in m["top_users"]} == {"maria@raizes.org.br"}


def test_eventos_de_seguranca_escopados_ao_tenant(client, seed):
    _super(client)  # gera evento de login da TeIA
    login(client, "maria@raizes.org.br", "senha-maria-123")
    token = _tenant_admin(client)
    res = client.get("/api/admin/metrics", headers=auth_headers(token))
    assert res.status_code == 200
    emails = {e["email"] for e in res.json()["security"]["recent_auth"]}
    assert "admin@teia.org.br" not in emails
    assert "maria@raizes.org.br" in emails
