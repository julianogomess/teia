"""Pipeline de ingestão: modelos, tags hierárquicas e processamento."""

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
