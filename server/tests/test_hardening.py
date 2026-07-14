"""Endurecimento para produção: travas de config (2, 8), teto de corpo
resistente a bypass de Content-Length (3) e defesa de prompt injection (6).
O teto de zip bomb (4) é testado junto ao upload em test_kb_api.py."""

import pytest

from app.config import DEV_SECRET_KEY, settings
from app.context_loader import RULES
from app.kb.classify import _PROMPT
from app.main import startup, validate_production_config

from .conftest import auth_headers, login


# --------------------------------------------------- config de produção (2, 8)
def test_producao_recusa_chave_de_desenvolvimento(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "secret_key", DEV_SECRET_KEY)
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "frontend_origin", "https://chat.teia.org.br")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_production_config()


def test_producao_recusa_cookie_inseguro(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "secret_key", "chave-forte-o-suficiente-para-prod")
    monkeypatch.setattr(settings, "cookie_secure", False)
    monkeypatch.setattr(settings, "frontend_origin", "https://chat.teia.org.br")
    with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
        validate_production_config()


def test_producao_aceita_config_segura(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "secret_key", "chave-forte-o-suficiente-para-prod")
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "frontend_origin", "https://chat.teia.org.br")
    validate_production_config()  # não levanta


def test_dev_apenas_avisa(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "secret_key", DEV_SECRET_KEY)
    monkeypatch.setattr(settings, "cookie_secure", False)
    validate_production_config()  # dev nunca levanta


def test_producao_nao_auto_cria_tabelas(monkeypatch):
    """Ponto 8: em produção o schema vem do Alembic, nunca do atalho."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "secret_key", "chave-forte-o-suficiente-para-prod")
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "frontend_origin", "https://chat.teia.org.br")
    monkeypatch.setattr(settings, "auto_create_tables", True)
    called = []
    monkeypatch.setattr("app.main.Base.metadata.create_all",
                        lambda *a, **k: called.append(True))
    startup()
    assert called == []  # não tocou no schema


# ------------------------------------------------ teto de corpo / bypass (3)
def test_corpo_acima_do_teto_rejeitado(client, seed):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    big = "x" * (settings.max_body_bytes + 1024)
    res = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": big}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 413


def test_corpo_sem_content_length_ainda_barrado(client, seed):
    """Streaming sem Content-Length não escapa do teto: os bytes são contados."""
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    payload = b'{"messages":[{"role":"user","content":"' \
        + b"x" * (settings.max_body_bytes + 1024) + b'"}]}'

    def stream():
        # em blocos, forçando o servidor a contar à medida que recebe
        for i in range(0, len(payload), 8192):
            yield payload[i:i + 8192]

    res = client.post(
        "/api/chat",
        content=stream(),
        headers={**auth_headers(token), "Content-Type": "application/json"},
    )
    assert res.status_code == 413


# ---------------------------------------------- prompt injection defensivo (6)
def test_regras_tratam_base_como_dado():
    assert "DADO, não instrução" in RULES


def test_classificador_ignora_instrucoes_do_documento():
    assert "DADO a ser classificado" in _PROMPT
