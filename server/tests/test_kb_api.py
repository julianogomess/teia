"""Rotas admin da base de conhecimento: upload, listagem, tags e isolamento."""

import io
import zipfile

import pytest

from app.kb import worker
from app.models import Document, Tag, User
from app.security import hash_password

from .conftest import TestingSession, auth_headers, login


@pytest.fixture()
def ong_admin(db, seed):
    admin = User(email="chefe@raizes.org.br", role="admin",
                 organization_id=seed["ong"].id,
                 password_hash=hash_password("senha-chefe-123"))
    db.add(admin)
    db.commit()
    return admin


@pytest.fixture()
def ong_token(client, ong_admin):
    return login(client, "chefe@raizes.org.br", "senha-chefe-123")


@pytest.fixture(autouse=True)
def _worker_session(monkeypatch):
    monkeypatch.setattr(worker, "SessionLocal", TestingSession)
    monkeypatch.setattr("app.kb.classify.classify_document", lambda *a, **k: [])


def _upload(client, token, name, data):
    return client.post(
        "/api/admin/documents", headers=auth_headers(token),
        files=[("files", (name, data, "application/octet-stream"))],
    )


def test_upload_e_processamento(client, db, seed, ong_token):
    res = _upload(client, ong_token, "ferias.md", b"regras de ferias do time")
    assert res.status_code == 202
    assert res.json()["created"] == ["ferias.md"]
    worker.process_pending()
    docs = client.get("/api/admin/documents",
                      headers=auth_headers(ong_token)).json()["documents"]
    assert docs[0]["status"] == "indexed"


def test_upload_zip_expande_e_filtra(client, db, seed, ong_token):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.md", "conteudo a")
        zf.writestr("sub/b.txt", "conteudo b")
        zf.writestr("virus.exe", "MZ")
    res = _upload(client, ong_token, "lote.zip", buf.getvalue())
    assert res.status_code == 202
    body = res.json()
    assert sorted(body["created"]) == ["a.md", "b.txt"]
    assert body["skipped"][0]["filename"] == "virus.exe"


def test_upload_extensao_invalida(client, ong_token):
    res = _upload(client, ong_token, "nota.exe", b"MZ")
    assert res.status_code == 202
    assert res.json()["skipped"][0]["reason"] == "formato"


def test_member_nao_acessa(client, seed):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    res = client.get("/api/admin/documents", headers=auth_headers(token))
    assert res.status_code == 403


def test_isolamento_admin_de_outro_tenant(client, db, seed, ong_token):
    _upload(client, ong_token, "segredo.md", b"dados internos da ong")
    teia_token = login(client, "admin@teia.org.br", "senha-admin-123")
    docs = client.get("/api/admin/documents",
                      headers=auth_headers(teia_token)).json()["documents"]
    assert docs == []  # admin da TeIA não vê documentos da ONG
    doc_id = db.query(Document).one().id
    res = client.delete(f"/api/admin/documents/{doc_id}",
                        headers=auth_headers(teia_token))
    assert res.status_code == 404


def test_delete_documento(client, db, seed, ong_token):
    _upload(client, ong_token, "tmp.md", b"conteudo temporario")
    doc_id = db.query(Document).one().id
    res = client.delete(f"/api/admin/documents/{doc_id}",
                        headers=auth_headers(ong_token))
    assert res.status_code == 200
    assert db.query(Document).count() == 0


def test_tags_criar_aprovar_rejeitar(client, db, seed, ong_token):
    res = client.post("/api/admin/tags", headers=auth_headers(ong_token),
                      json={"path": "RH/Benefícios"})
    assert res.status_code == 201
    db.add(Tag(organization_id=seed["ong"].id, path="rh/proposta",
               status="pending", source="ia"))
    db.commit()
    pending = [t for t in client.get("/api/admin/tags",
               headers=auth_headers(ong_token)).json()["tags"]
               if t["status"] == "pending"]
    assert pending[0]["path"] == "rh/proposta"
    res = client.patch(f"/api/admin/tags/{pending[0]['id']}",
                       headers=auth_headers(ong_token),
                       json={"status": "approved"})
    assert res.status_code == 200
    assert db.query(Tag).filter_by(path="rh/proposta").one().status == "approved"


def test_kb_search_do_admin(client, db, seed, ong_token):
    _upload(client, ong_token, "orc.md", b"o orcamento anual foi aprovado")
    worker.process_pending()
    res = client.get("/api/admin/kb-search", params={"q": "orcamento"},
                     headers=auth_headers(ong_token))
    assert res.status_code == 200
    assert "orcamento" in res.json()["hits"][0]["text"]
