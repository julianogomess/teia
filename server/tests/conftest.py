"""Fixtures: banco SQLite em memória, app com dependência de DB substituída,
usuários de teste e mock da chamada à Anthropic."""

import os
import sys
import tempfile
from pathlib import Path

# ambiente de teste ANTES de importar a app
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("TEIA_KB_WORKER_ENABLED", "false")
os.environ.setdefault("TEIA_UPLOAD_DIR", tempfile.mkdtemp(prefix="teia-uploads-"))
os.environ.pop("VOYAGE_API_KEY", None)  # nenhum teste chama a API real
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Organization, User
from app.rate_limit import chat_concurrency, chat_limiter, login_limiter
from app.security import hash_password

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def clean_state():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    login_limiter.reset()
    chat_limiter.reset()
    chat_concurrency.reset()
    from app.kb import search as kb_search
    kb_search.reset_cache()
    yield


@pytest.fixture()
def db():
    session = TestingSession()
    yield session
    session.close()


@pytest.fixture()
def seed(db):
    """Duas orgs (teia, ong), um admin (teia) e um member (ong)."""
    teia = Organization(
        slug="teia", name="TeIA", description="docs da TeIA",
        context_dir="context", api_key_env="ANTHROPIC_API_KEY_TEIA",
    )
    ong = Organization(
        slug="ong", name="Instituto Raízes do Amanhã", description="docs da ONG",
        context_dir="examples-ong", api_key_env="ANTHROPIC_API_KEY_ONG",
    )
    db.add_all([teia, ong])
    db.flush()
    admin = User(
        email="admin@teia.org.br", role="admin", organization_id=teia.id,
        password_hash=hash_password("senha-admin-123"),
    )
    member = User(
        email="maria@raizes.org.br", role="member", organization_id=ong.id,
        password_hash=hash_password("senha-maria-123"),
    )
    db.add_all([admin, member])
    db.commit()
    return {"teia": teia, "ong": ong, "admin": admin, "member": member}


@pytest.fixture()
def client():
    return TestClient(app)


def login(client, email, password):
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def fake_anthropic(monkeypatch):
    """Substitui a chamada real ao modelo; captura o que seria enviado."""
    calls = []

    def fake_send(api_key, system_blocks, messages, model=None):
        calls.append({"api_key": api_key, "system": system_blocks, "messages": messages})
        usage = {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        return "resposta de teste", usage, 42

    monkeypatch.setattr("app.routers.chat.send_message", fake_send)
    return calls
