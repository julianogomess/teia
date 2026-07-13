"""Unidades do pipeline: extração, chunking, embeddings e classificação."""

import io

import pytest

from app.kb.chunking import split_chunks
from app.kb.extract import UnsupportedFormat, extract_text


def _pdf_bytes() -> bytes:
    """Gera um PDF de uma página com pypdf (sem dependência extra)."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_extrai_md_e_txt():
    assert extract_text("a.md", "## Férias\ntexto".encode("utf-8")) == "## Férias\ntexto"
    assert extract_text("b.TXT", b"plano") == "plano"


def test_extrai_pdf_sem_erro():
    # página em branco: extração retorna string (vazia), sem explodir
    assert isinstance(extract_text("c.pdf", _pdf_bytes()), str)


def test_formato_nao_suportado():
    with pytest.raises(UnsupportedFormat):
        extract_text("virus.exe", b"MZ")


def test_chunk_unico_para_texto_curto():
    assert split_chunks("pequeno", max_chars=100, overlap=10) == ["pequeno"]


def test_chunks_com_sobreposicao():
    paras = "\n\n".join(f"parágrafo {i} " + "x" * 80 for i in range(10))
    chunks = split_chunks(paras, max_chars=300, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 300 + 50 for c in chunks)
    # sobreposição: o fim de um chunk reaparece no começo do seguinte
    assert chunks[0][-30:] in chunks[1]


def test_paragrafo_gigante_e_quebrado():
    chunks = split_chunks("y" * 1000, max_chars=300, overlap=50)
    assert len(chunks) >= 3


def test_texto_vazio():
    assert split_chunks("   \n\n  ", max_chars=100, overlap=10) == []


# ------------------------------------------------------------------ embeddings

from app.kb.embeddings import (  # noqa: E402
    EmbeddingError,
    bytes_to_matrix,
    cosine_scores,
    embed_texts,
    embedding_to_bytes,
)


def test_embedding_bytes_ida_e_volta():
    blob = embedding_to_bytes([1.0, 0.0, 0.0])
    matrix = bytes_to_matrix([blob, embedding_to_bytes([0.0, 1.0, 0.0])])
    assert matrix.shape == (2, 3)
    scores = cosine_scores(matrix, [1.0, 0.0, 0.0])
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.0)


def test_embed_texts_chama_voyage(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(json)
        return FakeResponse()

    monkeypatch.setenv("VOYAGE_API_KEY", "chave-teste")
    monkeypatch.setattr("app.kb.embeddings.httpx.post", fake_post)
    vecs = embed_texts(["a", "b"], "document")
    assert vecs == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["input_type"] == "document"
    assert captured["output_dimension"] == 512


def test_embed_texts_sem_chave(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(EmbeddingError):
        embed_texts(["a"], "query")


# --------------------------------------------------------------- classificação

from app.kb.classify import classify_document, normalize_path  # noqa: E402


def test_normaliza_caminhos_de_tag():
    assert normalize_path(" RH / Benefícios / Férias ") == "rh/benefícios/férias"
    assert normalize_path("a//b") == "a/b"
    assert normalize_path("a/b/c/d/e") == "a/b/c/d"  # profundidade máxima 4
    assert normalize_path("///") is None
    assert normalize_path("x" * 300) is None


def test_classifica_documento(monkeypatch):
    def fake_send(api_key, system_blocks, messages, model=None):
        return ('["rh/beneficios/ferias", "RH/Contratos", "///"]',
                {"input_tokens": 10}, 5)

    monkeypatch.setattr("app.kb.classify.send_message", fake_send)
    tags = classify_document("chave", ["rh/beneficios"], "ferias.md", "texto")
    assert tags == ["rh/beneficios/ferias", "rh/contratos"]


def test_classificacao_resposta_invalida(monkeypatch):
    def fake_send(api_key, system_blocks, messages, model=None):
        return ("não sei classificar", {}, 5)

    monkeypatch.setattr("app.kb.classify.send_message", fake_send)
    assert classify_document("chave", [], "a.md", "texto") == []
