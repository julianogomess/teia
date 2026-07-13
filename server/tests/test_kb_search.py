"""Busca híbrida: termos, vetores, bônus de tag e isolamento entre tenants."""

import pytest

from app.kb import pipeline, search
from app.kb.embeddings import embedding_to_bytes
from app.kb.search import search_chunks
from app.models import Document, DocumentChunk, DocumentTag

# vetores de brinquedo: "férias" e "descanso" apontam na mesma direção
VECTORS = {
    "férias": [1.0, 0.0, 0.0],
    "descanso": [0.9, 0.1, 0.0],
    "orçamento": [0.0, 1.0, 0.0],
    "outro": [0.0, 0.0, 1.0],
}


def _vec(text):
    for word, vec in VECTORS.items():
        if word in text.lower():
            return vec
    return VECTORS["outro"]


@pytest.fixture()
def fake_embeddings(monkeypatch):
    monkeypatch.setattr("app.kb.embeddings.resolve_voyage_key", lambda: "chave")
    monkeypatch.setattr(
        "app.kb.embeddings.embed_texts",
        lambda texts, input_type: [_vec(t) for t in texts],
    )


def _add_doc(db, org_id, filename, chunks, tag_path=None, embed=True):
    doc = Document(organization_id=org_id, filename=filename, ext=".md",
                   content_hash=filename, stored_path=f"x/{filename}",
                   status="indexed", chunk_count=len(chunks))
    db.add(doc)
    db.flush()
    for i, text in enumerate(chunks):
        db.add(DocumentChunk(
            document_id=doc.id, organization_id=org_id, position=i, text=text,
            embedding=embedding_to_bytes(_vec(text)) if embed else None,
        ))
    if tag_path:
        leaf = pipeline.ensure_tags(db, org_id, [tag_path],
                                    status="approved", source="admin")[0]
        db.add(DocumentTag(document_id=doc.id, tag_id=leaf.id))
    db.commit()
    search.invalidate(org_id)
    return doc


def test_busca_por_termo_exato(db, seed):
    org = seed["ong"]
    _add_doc(db, org.id, "orc.md",
             ["o orçamento anual foi aprovado", "outro assunto qualquer"],
             embed=False)
    hits = search_chunks(db, org.id, "como ficou o orçamento?")
    assert hits and "orçamento" in hits[0].text


def test_busca_semantica_acha_sinonimo(db, seed, fake_embeddings):
    org = seed["ong"]
    _add_doc(db, org.id, "rh.md",
             ["política de descanso remunerado da equipe",
              "outro assunto qualquer"])
    hits = search_chunks(db, org.id, "como funcionam as férias?")
    assert hits and "descanso" in hits[0].text


def test_bonus_de_tag_aprovada(db, seed):
    org = seed["ong"]
    _add_doc(db, org.id, "a.md", ["orçamento geral da entidade"], embed=False)
    _add_doc(db, org.id, "b.md", ["orçamento do projeto educação"],
             tag_path="financeiro/orçamento", embed=False)
    hits = search_chunks(db, org.id, "orçamento")
    assert hits[0].filename == "b.md"
    assert "financeiro/orçamento" in hits[0].tags


def test_isolamento_entre_tenants(db, seed):
    ong, teia = seed["ong"], seed["teia"]
    _add_doc(db, ong.id, "segredo.md", ["orçamento secreto da ong"], embed=False)
    assert search_chunks(db, teia.id, "orçamento secreto") == []


def test_sem_resultado(db, seed):
    org = seed["ong"]
    _add_doc(db, org.id, "a.md", ["conteúdo qualquer"], embed=False)
    assert search_chunks(db, org.id, "zzz inexistente") == []
    assert search_chunks(db, org.id, "de a o") == []  # só stopwords
