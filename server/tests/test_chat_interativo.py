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


def _chat(client, token, texto="oi"):
    return client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": texto}]},
        headers=auth_headers(token),
    )


def test_chat_retorna_opcoes(client, seed, fake_anthropic):
    fake_anthropic.tool_input = {
        "opcoes": ["Como funciona o reembolso?", "Quais são os prazos?"]}
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    data = _chat(client, token).json()
    assert data["reply"] == "resposta de teste"
    assert data["options"] == [
        "Como funciona o reembolso?", "Quais são os prazos?"]
    # a ferramenta foi oferecida ao modelo
    assert fake_anthropic[0]["tools"][0]["name"] == "sugerir_continuacoes"


def test_chat_sem_opcoes(client, seed, fake_anthropic):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert _chat(client, token).json()["options"] == []


def test_opcoes_validadas_e_truncadas(client, seed, fake_anthropic):
    fake_anthropic.tool_input = {"opcoes": [
        "   ", "x" * 200, 42, "a", "b", "c", "d"]}
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    options = _chat(client, token).json()["options"]
    assert options == ["x" * 80, "a", "b", "c"]  # máx. 4, 80 chars, sem lixo


def test_tool_input_malformado(client, seed, fake_anthropic):
    fake_anthropic.tool_input = {"foo": "bar"}
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert _chat(client, token).json()["options"] == []


def test_regras_permitem_markdown_e_ferramenta(client, seed, fake_anthropic):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    _chat(client, token)
    system_text = "\n".join(b["text"] for b in fake_anthropic[0]["system"])
    assert "sugerir_continuacoes" in system_text
    assert "Markdown leve" in system_text


def test_ferramenta_sem_texto_segue_sem_opcoes(client, seed, fake_anthropic):
    fake_anthropic.reply = ""
    fake_anthropic.tool_input = {"opcoes": ["a", "b"]}
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    data = _chat(client, token).json()
    assert data["reply"] == ""
    assert data["options"] == []
