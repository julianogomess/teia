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
