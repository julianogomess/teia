"""Pipeline de ingestão: modelos, tags hierárquicas e processamento."""

from pathlib import Path

from app.kb import pipeline
from app.kb.pipeline import (
    delete_document,
    ensure_tags,
    process_document,
    register_document,
)
from app.models import Document, DocumentChunk, DocumentTag, IngestJob, Tag


def test_modelos_da_base_de_conhecimento(db, seed):
    org = seed["ong"]
    doc = Document(
        organization_id=org.id, filename="ferias.md", ext=".md",
        content_hash="abc123", stored_path="uploads/ong/abc123.md",
    )
    db.add(doc)
    db.flush()
    db.add(DocumentChunk(document_id=doc.id, organization_id=org.id,
                         position=0, text="políticas de férias"))
    tag = Tag(organization_id=org.id, path="rh/beneficios/ferias",
              status="pending", source="ia")
    db.add(tag)
    db.flush()
    db.add(DocumentTag(document_id=doc.id, tag_id=tag.id))
    db.add(IngestJob(document_id=doc.id))
    db.commit()

    assert doc.status == "pending"
    assert db.query(IngestJob).one().status == "pending"


def test_ensure_tags_cria_hierarquia_pendente(db, seed):
    org = seed["ong"]
    leaves = ensure_tags(db, org.id, ["rh/beneficios/ferias"])
    db.commit()
    paths = {t.path: t for t in db.query(Tag).all()}
    assert set(paths) == {"rh", "rh/beneficios", "rh/beneficios/ferias"}
    assert all(t.status == "pending" and t.source == "ia" for t in paths.values())
    assert [t.path for t in leaves] == ["rh/beneficios/ferias"]


def test_ensure_tags_nao_duplica_nem_rebaixa(db, seed):
    org = seed["ong"]
    db.add(Tag(organization_id=org.id, path="rh", status="approved"))
    db.commit()
    ensure_tags(db, org.id, ["rh/contratos"])
    db.commit()
    rh_tags = db.query(Tag).filter_by(path="rh").all()
    assert len(rh_tags) == 1
    assert rh_tags[0].status == "approved"  # tag existente não volta a pendente


def test_register_document_dedup_e_substituicao(db, seed):
    org = seed["ong"]
    doc, reason = register_document(db, org, "ferias.md", b"conteudo v1")
    db.commit()
    assert reason == "criado" and doc.status == "pending"
    assert (pipeline.upload_root() / org.slug).exists()

    _, reason = register_document(db, org, "copia.md", b"conteudo v1")
    assert reason == "duplicado"  # mesmo hash no mesmo tenant

    doc2, reason = register_document(db, org, "ferias.md", b"conteudo v2")
    db.commit()
    assert reason == "substituido"
    assert db.query(Document).filter_by(organization_id=org.id).count() == 1
    assert doc2.content_hash != doc.content_hash

    _, reason = register_document(db, org, "nota.exe", b"MZ")
    assert reason == "formato"
    _, reason = register_document(db, org, "vazio.md", b"")
    assert reason == "vazio"


def test_process_document_indexa(db, seed, monkeypatch):
    org = seed["ong"]
    monkeypatch.setattr(
        "app.kb.classify.classify_document",
        lambda *a, **k: ["rh/beneficios/ferias"],
    )
    monkeypatch.setattr("app.kb.embeddings.resolve_voyage_key", lambda: "chave")
    monkeypatch.setattr(
        "app.kb.embeddings.embed_texts",
        lambda texts, input_type: [[1.0, 0.0] for _ in texts],
    )
    doc, _ = register_document(db, org, "ferias.md", "política de férias " * 400)
    db.commit()
    process_document(db, doc.id)
    db.refresh(doc)
    assert doc.status == "indexed"
    assert doc.chunk_count > 1
    chunks = db.query(DocumentChunk).filter_by(document_id=doc.id).all()
    assert all(c.embedding is not None and c.organization_id == org.id
               for c in chunks)
    assert db.query(DocumentTag).filter_by(document_id=doc.id).count() == 1


def test_process_document_erro_vira_status_error(db, seed):
    org = seed["ong"]
    doc, _ = register_document(db, org, "quebrado.pdf", b"nao sou um pdf")
    db.commit()
    process_document(db, doc.id)
    db.refresh(doc)
    assert doc.status == "error"
    assert doc.error


def test_worker_processa_fila(db, seed, monkeypatch):
    from app.kb import worker

    from .conftest import TestingSession

    monkeypatch.setattr(worker, "SessionLocal", TestingSession)
    monkeypatch.setattr("app.kb.classify.classify_document", lambda *a, **k: [])
    org = seed["ong"]
    register_document(db, org, "um.md", b"conteudo um bem interessante")
    register_document(db, org, "dois.md", b"conteudo dois diferente")
    db.commit()

    assert worker.process_pending() == 2
    statuses = {d.filename: d.status for d in db.query(Document).all()}
    assert statuses == {"um.md": "indexed", "dois.md": "indexed"}
    assert {j.status for j in db.query(IngestJob).all()} == {"done"}


def test_delete_document_limpa_tudo(db, seed, monkeypatch):
    org = seed["ong"]
    monkeypatch.setattr("app.kb.classify.classify_document", lambda *a, **k: [])
    doc, _ = register_document(db, org, "x.md", b"algum conteudo aqui")
    db.commit()
    process_document(db, doc.id)
    stored = Path(doc.stored_path)
    assert stored.exists()
    delete_document(db, doc)
    db.commit()
    assert db.query(Document).count() == 0
    assert db.query(DocumentChunk).count() == 0
    assert not stored.exists()
