"""Chat interativo: fontes consultadas e (Task 3) opções sugeridas."""

from app import context_loader
from app.kb.search import ChunkHit

from .conftest import auth_headers, login


def _hit(filename, tags, text="trecho"):
    return ChunkHit(chunk_id=1, document_id=1, filename=filename,
                    text=text, tags=tags, score=1.0)


def test_build_system_blocks_devolve_fontes(monkeypatch, db, seed):
    monkeypatch.setattr(context_loader, "has_indexed_documents",
                        lambda db, org_id: True)
    hits = [
        _hit("manual.pdf", ["rh/beneficios"]),
        _hit("manual.pdf", ["rh/beneficios"], text="outro trecho"),
        _hit("guia.md", []),
    ]
    monkeypatch.setattr("app.kb.search.search_chunks",
                        lambda db, org_id, query, top_k=8: hits)
    blocks, sources = context_loader.build_system_blocks(
        seed["ong"], db=db, query="férias")
    assert sources == [
        {"filename": "manual.pdf", "tags": ["rh/beneficios"]},
        {"filename": "guia.md", "tags": []},
    ]
    assert "manual.pdf" in blocks[1]["text"]


def test_fallback_pasta_sem_fontes(db, seed):
    blocks, sources = context_loader.build_system_blocks(
        seed["ong"], db=db, query="oi")
    assert sources == []
    assert len(blocks) == 2


def test_chat_responde_sources(client, seed, fake_anthropic):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    res = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "oi"}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    assert res.json()["sources"] == []
