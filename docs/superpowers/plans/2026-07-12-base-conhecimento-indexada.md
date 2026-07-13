# Base de Conhecimento Indexada — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingestão de grandes volumes de arquivos (.md/.txt/.pdf) por tenant, com classificação automática em tags hierárquicas, indexação e busca híbrida (tags + termos + vetorial) para que o chat injete só os trechos relevantes por pergunta.

**Architecture:** Tudo no banco existente (SQLite dev / Postgres prod) em novas tabelas isoladas por `organization_id`; pipeline assíncrono com fila em tabela e worker em thread; embeddings Voyage guardados como bytes float32 e pontuados com numpy; classificação via Haiku contra taxonomia por tenant; `/api/chat` troca a base inteira por top-k chunks quando o tenant tem documentos indexados.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, httpx, pypdf, python-multipart, numpy, API Voyage (embeddings), API Anthropic (classificação).

## Global Constraints

- Python 3.9 (usar `Optional[X]`/`List[X]` de `typing`, nunca `X | Y`); rodar com `py`.
- Comentários e mensagens de erro em pt-BR, no tom do código existente (ver `server/app/*.py`).
- Toda query de dados novos filtra por `organization_id`.
- Testes rodam em SQLite in-memory (conftest existente); worker desligado em teste (`TEIA_KB_WORKER_ENABLED=false`); sem chamadas de rede em teste (Voyage/Anthropic sempre mockados).
- Módulos consumidores importam `from . import embeddings` / `from . import classify` (patch único em teste), nunca `from .embeddings import embed_texts`.
- Spec: `docs/superpowers/specs/2026-07-12-base-conhecimento-indexada-design.md`.
- Comandos de teste a partir de `server/`: `py -m pytest tests -q`.
- Commits frequentes, mensagem em inglês no padrão do repo, rodapé `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Dependências, config, modelos e migração

**Files:**
- Modify: `server/requirements.txt`
- Modify: `server/app/config.py` (bloco novo de settings)
- Modify: `server/app/models.py` (5 tabelas novas)
- Modify: `server/tests/conftest.py` (env do worker/uploads antes do import)
- Modify: `.gitignore` (server/uploads/)
- Create: `server/alembic/versions/a1f2c3d4e5f6_base_conhecimento.py`
- Test: `server/tests/test_kb_pipeline.py` (só o teste de modelos nesta task)

**Interfaces:**
- Produces: modelos `Document`, `DocumentChunk`, `Tag`, `DocumentTag`, `IngestJob` (campos abaixo); settings `kb_*`, `voyage_*`, `upload_dir`.

- [ ] **Step 1: Instalar dependências novas e registrá-las**

Em `server/requirements.txt`, acrescentar ao final:

```
pypdf>=4.0            # extração de texto de PDF (fase 1 da base de conhecimento)
python-multipart>=0.0.9  # upload de arquivos no FastAPI
numpy>=1.24,<2.1      # pontuação vetorial da busca híbrida
```

Rodar: `cd server && py -m pip install -r requirements.txt`
Esperado: instalação sem erro.

- [ ] **Step 2: Settings novos em `config.py`**

Adicionar dentro de `class Settings`, após o bloco `--- Anthropic ---`:

```python
    # --- base de conhecimento (ingestão e busca) ----------------------------
    kb_worker_enabled: bool = True           # thread de ingestão no startup
    kb_chunk_chars: int = 2800               # ~700 tokens por chunk
    kb_chunk_overlap_chars: int = 300        # sobreposição entre chunks
    kb_top_k: int = 8                        # chunks injetados por pergunta
    kb_max_upload_bytes: int = 50 * 1024 * 1024  # corpo máximo no upload
    kb_classify_model: str = "claude-haiku-4-5"  # classificação de tags
    kb_classify_excerpt_chars: int = 6000    # trecho enviado ao classificador
    upload_dir: str = "uploads"              # originais; relativo a server/
    # Embeddings (Voyage). A chave vem de VOYAGE_API_KEY, sem prefixo,
    # como as chaves da Anthropic — nunca no banco.
    voyage_api_url: str = "https://api.voyageai.com/v1/embeddings"
    voyage_model: str = "voyage-3.5-lite"
    voyage_output_dim: int = 512
    voyage_timeout_seconds: int = 60
```

- [ ] **Step 3: Teste que falha — modelos**

Criar `server/tests/test_kb_pipeline.py`:

```python
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
```

Rodar: `py -m pytest tests/test_kb_pipeline.py -q` → FAIL (ImportError).

- [ ] **Step 4: Modelos em `models.py`**

Acrescentar ao final de `server/app/models.py` (e citar as tabelas novas no docstring do módulo):

```python
# --- base de conhecimento ----------------------------------------------------
# documents       -> arquivo ingerido por tenant (original fica no disco)
# document_chunks -> trechos de ~700 tokens; embedding opcional (float32 bytes)
# tags            -> taxonomia hierárquica por tenant (caminho materializado)
# document_tags   -> associação documento<->tag
# ingest_jobs     -> fila de processamento no próprio banco

DOCUMENT_STATUSES = ("pending", "processing", "indexed", "error")
TAG_STATUSES = ("approved", "pending", "rejected")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    ext: Mapped[str] = mapped_column(String(10))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    # caminho do original, relativo a server/ (ou absoluto em testes)
    stored_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    # vetor float32 serializado; NULL quando embeddings estão desligados
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)

    document: Mapped["Document"] = relationship()


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("organization_id", "path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    # caminho materializado ("rh/beneficios/ferias"): consulta por prefixo
    # cobre qualquer nível da hierarquia com o índice comum
    path: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default="approved")
    source: Mapped[str] = mapped_column(String(20), default="admin")  # admin | ia
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentTag(Base):
    __tablename__ = "document_tags"
    __table_args__ = (UniqueConstraint("document_id", "tag_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), index=True)

    tag: Mapped["Tag"] = relationship()


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    # pending | running | done | error
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

Ajustar o import no topo do arquivo para incluir `LargeBinary` e `UniqueConstraint`:

```python
from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text,
    UniqueConstraint,
)
```

- [ ] **Step 5: conftest — worker desligado, uploads em pasta temporária, sem chave Voyage**

Em `server/tests/conftest.py`, logo após o `os.environ.setdefault("ANTHROPIC_API_KEY", ...)`:

```python
import tempfile

os.environ.setdefault("TEIA_KB_WORKER_ENABLED", "false")
os.environ.setdefault("TEIA_UPLOAD_DIR", tempfile.mkdtemp(prefix="teia-uploads-"))
os.environ.pop("VOYAGE_API_KEY", None)  # nenhum teste chama a API real
```

E no fixture `clean_state`, antes do `yield`:

```python
    from app.kb import search as kb_search
    kb_search.reset_cache()
```

(`reset_cache` nasce na Task 6; até lá, deixar essas duas linhas comentadas e descomentá-las na Task 6.)

- [ ] **Step 6: Migração Alembic**

Criar `server/alembic/versions/a1f2c3d4e5f6_base_conhecimento.py`:

```python
"""base de conhecimento: documents, chunks, tags, jobs

Revision ID: a1f2c3d4e5f6
Revises: cb9d6d7244b1
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "a1f2c3d4e5f6"
down_revision = "cb9d6d7244b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer,
                  sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("ext", sa.String(10), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, index=True),
        sa.Column("stored_path", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending", index=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer,
                  sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("organization_id", sa.Integer,
                  sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", sa.LargeBinary, nullable=True),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer,
                  sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("path", sa.String(255), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="approved"),
        sa.Column("source", sa.String(20), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("organization_id", "path"),
    )
    op.create_table(
        "document_tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer,
                  sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("tag_id", sa.Integer,
                  sa.ForeignKey("tags.id"), nullable=False, index=True),
        sa.UniqueConstraint("document_id", "tag_id"),
    )
    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer,
                  sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending", index=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ingest_jobs")
    op.drop_table("document_tags")
    op.drop_table("tags")
    op.drop_table("document_chunks")
    op.drop_table("documents")
```

- [ ] **Step 7: `.gitignore`** — acrescentar linha `server/uploads/`.

- [ ] **Step 8: Rodar testes**

`py -m pytest tests -q` → tudo verde (o teste novo passa; suite antiga intacta).

- [ ] **Step 9: Commit**

```bash
git add server/requirements.txt server/app/config.py server/app/models.py server/tests/conftest.py server/tests/test_kb_pipeline.py server/alembic/versions/a1f2c3d4e5f6_base_conhecimento.py .gitignore
git commit -m "feat: add knowledge-base models, settings and migration"
```

---

### Task 2: Extração e chunking (`app/kb/extract.py`, `app/kb/chunking.py`)

**Files:**
- Create: `server/app/kb/__init__.py` (vazio)
- Create: `server/app/kb/extract.py`
- Create: `server/app/kb/chunking.py`
- Test: `server/tests/test_kb_units.py`

**Interfaces:**
- Produces: `ALLOWED_EXTENSIONS: Tuple[str, ...]`, `class UnsupportedFormat(Exception)`, `extract_text(filename: str, data: bytes) -> str`, `split_chunks(text: str, max_chars: Optional[int] = None, overlap: Optional[int] = None) -> List[str]`.

- [ ] **Step 1: Testes que falham**

Criar `server/tests/test_kb_units.py`:

```python
"""Unidades do pipeline: extração, chunking, embeddings e classificação."""

import io

import pytest

from app.kb.chunking import split_chunks
from app.kb.extract import UnsupportedFormat, extract_text


def _pdf_bytes(text: str) -> bytes:
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
    assert isinstance(extract_text("c.pdf", _pdf_bytes("x")), str)


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
```

Rodar: `py -m pytest tests/test_kb_units.py -q` → FAIL (ImportError).

- [ ] **Step 2: Implementar `extract.py`**

```python
"""Extração de texto dos formatos aceitos na fase 1 (.md, .txt, .pdf)."""

import io
from pathlib import Path

ALLOWED_EXTENSIONS = (".md", ".txt", ".pdf")


class UnsupportedFormat(Exception):
    pass


def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".md", ".txt"):
        return data.decode("utf-8", errors="replace")
    if ext == ".pdf":
        from pypdf import PdfReader  # import tardio: só quem ingere PDF paga

        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(p for p in pages if p.strip())
    raise UnsupportedFormat(f"Formato não suportado: {ext or filename}")
```

- [ ] **Step 3: Implementar `chunking.py`**

```python
"""Divisão do texto em chunks de ~700 tokens com sobreposição.

Corta por parágrafos para não partir frases; parágrafos maiores que o
limite são quebrados à força. A sobreposição repete o final do chunk
anterior no seguinte, para não perder contexto na fronteira.
"""

from typing import List, Optional

from ..config import settings


def split_chunks(text: str, max_chars: Optional[int] = None,
                 overlap: Optional[int] = None) -> List[str]:
    max_chars = max_chars or settings.kb_chunk_chars
    overlap = overlap if overlap is not None else settings.kb_chunk_overlap_chars

    paragraphs: List[str] = []
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        while len(para) > max_chars:  # parágrafo maior que o limite
            paragraphs.append(para[:max_chars])
            para = para[max_chars - overlap:]
        paragraphs.append(para)

    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = (chunks[-1][-overlap:] + "\n\n" + para) if (chunks and overlap) else para
    if current:
        chunks.append(current)
    return chunks
```

- [ ] **Step 4: Rodar** `py -m pytest tests/test_kb_units.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/kb/__init__.py server/app/kb/extract.py server/app/kb/chunking.py server/tests/test_kb_units.py
git commit -m "feat: add text extraction (md/txt/pdf) and chunking"
```

---

### Task 3: Embeddings Voyage (`app/kb/embeddings.py`)

**Files:**
- Create: `server/app/kb/embeddings.py`
- Test: `server/tests/test_kb_units.py` (acrescentar)

**Interfaces:**
- Produces: `class EmbeddingError(Exception)`, `resolve_voyage_key() -> Optional[str]`, `embed_texts(texts: List[str], input_type: str) -> List[List[float]]` (input_type: `"document"` ou `"query"`), `embedding_to_bytes(vec: Sequence[float]) -> bytes`, `bytes_to_matrix(blobs: List[bytes]) -> np.ndarray` (normalizada por linha), `cosine_scores(matrix: np.ndarray, query_vec: Sequence[float]) -> np.ndarray`.

- [ ] **Step 1: Testes que falham** (acrescentar em `test_kb_units.py`)

```python
import numpy as np

from app.kb.embeddings import (
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
```

Rodar → FAIL (ImportError).

- [ ] **Step 2: Implementar `embeddings.py`**

```python
"""Cliente de embeddings (Voyage) e utilidades de vetor.

Os vetores são guardados como bytes float32 no banco — portátil entre
SQLite e Postgres — e pontuados com numpy (produto escalar de vetores
normalizados = cosseno). A chave vem de VOYAGE_API_KEY; sem chave, a
ingestão pula embeddings e a busca segue só com termos e tags.
"""

import os
from typing import List, Optional, Sequence

import httpx
import numpy as np

from ..config import settings

_BATCH = 128  # limite de itens por chamada da API


class EmbeddingError(Exception):
    pass


def resolve_voyage_key() -> Optional[str]:
    return os.environ.get("VOYAGE_API_KEY")


def embed_texts(texts: List[str], input_type: str) -> List[List[float]]:
    """Vetoriza textos. input_type: 'document' (ingestão) ou 'query' (busca)."""
    key = resolve_voyage_key()
    if not key:
        raise EmbeddingError("VOYAGE_API_KEY não configurada.")
    vectors: List[List[float]] = []
    for start in range(0, len(texts), _BATCH):
        batch = texts[start:start + _BATCH]
        try:
            response = httpx.post(
                settings.voyage_api_url,
                json={
                    "model": settings.voyage_model,
                    "input": batch,
                    "input_type": input_type,
                    "output_dimension": settings.voyage_output_dim,
                },
                headers={"Authorization": f"Bearer {key}"},
                timeout=settings.voyage_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Falha ao contatar a API de embeddings: {exc}")
        if response.status_code != 200:
            raise EmbeddingError(
                f"API de embeddings respondeu {response.status_code}: "
                f"{response.text[:200]}"
            )
        vectors.extend(item["embedding"] for item in response.json()["data"])
    return vectors


def embedding_to_bytes(vec: Sequence[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def bytes_to_matrix(blobs: List[bytes]) -> np.ndarray:
    """Matriz (n, dim) normalizada por linha, pronta para cosine_scores."""
    matrix = np.vstack([np.frombuffer(b, dtype=np.float32) for b in blobs])
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def cosine_scores(matrix: np.ndarray, query_vec: Sequence[float]) -> np.ndarray:
    query = np.asarray(query_vec, dtype=np.float32)
    norm = np.linalg.norm(query)
    if norm:
        query = query / norm
    return matrix @ query
```

- [ ] **Step 3: Rodar** `py -m pytest tests/test_kb_units.py -q` → PASS.

- [ ] **Step 4: Commit**

```bash
git add server/app/kb/embeddings.py server/tests/test_kb_units.py
git commit -m "feat: add Voyage embeddings client and vector scoring"
```

---

### Task 4: Classificação por tags via Haiku (`app/kb/classify.py`)

**Files:**
- Create: `server/app/kb/classify.py`
- Test: `server/tests/test_kb_units.py` (acrescentar)

**Interfaces:**
- Consumes: `app.anthropic_client.send_message(api_key, system_blocks, messages, model=...)`.
- Produces: `normalize_path(raw: str) -> Optional[str]`, `classify_document(api_key: str, taxonomy: List[str], filename: str, text: str) -> List[str]` (caminhos normalizados, máx. 5).

- [ ] **Step 1: Testes que falham** (acrescentar em `test_kb_units.py`)

```python
from app.kb.classify import classify_document, normalize_path


def test_normaliza_caminhos_de_tag():
    assert normalize_path(" RH / Benefícios / Férias ") == "rh/benefícios/férias"
    assert normalize_path("a//b") == "a/b"
    assert normalize_path("a/b/c/d/e") == "a/b/c/d"  # profundidade máxima 4
    assert normalize_path("///") is None
    assert normalize_path("x" * 300) is None


def test_classifica_documento(monkeypatch):
    def fake_send(api_key, system_blocks, messages, model=None):
        return ('["rh/beneficios/ferias", "RH/Contratos", "inválida//"]',
                {"input_tokens": 10}, 5)

    monkeypatch.setattr("app.kb.classify.send_message", fake_send)
    tags = classify_document("chave", ["rh/beneficios"], "ferias.md", "texto")
    assert tags == ["rh/beneficios/ferias", "rh/contratos"]


def test_classificacao_resposta_invalida(monkeypatch):
    def fake_send(api_key, system_blocks, messages, model=None):
        return ("não sei classificar", {}, 5)

    monkeypatch.setattr("app.kb.classify.send_message", fake_send)
    assert classify_document("chave", [], "a.md", "texto") == []
```

Rodar → FAIL.

- [ ] **Step 2: Implementar `classify.py`**

```python
"""Classificação de documentos em tags hierárquicas via Haiku.

A IA recebe a taxonomia atual do tenant e o começo do documento, e devolve
um JSON de caminhos ("rh/beneficios/ferias"). Caminhos fora da taxonomia
são aceitos — nascem como tags pendentes de aprovação do admin (pipeline).
"""

import json
import re
from typing import List, Optional

from ..anthropic_client import send_message
from ..config import settings

MAX_TAGS = 5
MAX_DEPTH = 4

_PROMPT = """Você classifica documentos internos de uma organização em tags
hierárquicas (formato: nivel1/nivel2/nivel3, minúsculas).

Taxonomia atual da organização (prefira SEMPRE reusar estes caminhos):
{taxonomy}

Classifique o documento abaixo. Responda APENAS com um array JSON de 1 a
{max_tags} caminhos de tag, do mais ao menos relevante. Só proponha um
caminho novo se nenhum existente servir.

Arquivo: {filename}
---
{text}"""


def normalize_path(raw: str) -> Optional[str]:
    parts = [p.strip().lower() for p in raw.split("/")]
    parts = [re.sub(r"\s+", "-", p) for p in parts if p]
    if not parts:
        return None
    path = "/".join(parts[:MAX_DEPTH])
    return path if len(path) <= 255 else None


def classify_document(api_key: str, taxonomy: List[str],
                      filename: str, text: str) -> List[str]:
    prompt = _PROMPT.format(
        taxonomy="\n".join(f"- {t}" for t in taxonomy) or "(vazia)",
        max_tags=MAX_TAGS,
        filename=filename,
        text=text[:settings.kb_classify_excerpt_chars],
    )
    reply, _usage, _latency = send_message(
        api_key,
        [{"type": "text", "text": "Você é um classificador de documentos."}],
        [{"role": "user", "content": prompt}],
        model=settings.kb_classify_model,
    )
    match = re.search(r"\[.*\]", reply, re.DOTALL)
    if not match:
        return []
    try:
        raw_paths = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    paths: List[str] = []
    for raw in raw_paths:
        if not isinstance(raw, str):
            continue
        path = normalize_path(raw)
        if path and path not in paths:
            paths.append(path)
    return paths[:MAX_TAGS]
```

- [ ] **Step 3: Rodar** `py -m pytest tests/test_kb_units.py -q` → PASS.

- [ ] **Step 4: Commit**

```bash
git add server/app/kb/classify.py server/tests/test_kb_units.py
git commit -m "feat: add Haiku-based hierarchical tag classification"
```

---

### Task 5: Pipeline de processamento (`app/kb/pipeline.py`)

**Files:**
- Create: `server/app/kb/pipeline.py`
- Test: `server/tests/test_kb_pipeline.py` (acrescentar)

**Interfaces:**
- Consumes: `extract_text`, `split_chunks`, `classify.classify_document`, `embeddings.embed_texts`/`embedding_to_bytes`/`resolve_voyage_key`, `anthropic_client.resolve_api_key`.
- Produces:
  - `upload_root() -> Path` (pasta dos originais; aceita `settings.upload_dir` absoluto ou relativo a server/)
  - `ensure_tags(db, org_id: int, paths: List[str], status: str = "pending", source: str = "ia") -> List[Tag]` (cria ancestrais; retorna as folhas)
  - `register_document(db, org: Organization, filename: str, data: bytes) -> Tuple[Optional[Document], str]` — razões: `"criado" | "substituido" | "duplicado" | "formato" | "vazio"`; cria `IngestJob` quando registra; **não** commita
  - `delete_document(db, document: Document) -> None` (chunks, links, jobs, arquivo; não commita)
  - `process_document(db, document_id: int) -> None` (commita; nunca levanta — grava status `error`)

- [ ] **Step 1: Testes que falham** (acrescentar em `test_kb_pipeline.py`)

```python
from pathlib import Path

from app.kb import pipeline
from app.kb.pipeline import (
    delete_document,
    ensure_tags,
    process_document,
    register_document,
)


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
    rh = db.query(Tag).filter_by(path="rh").one()
    assert rh.status == "approved"  # tag existente não volta a pendente
    assert db.query(Tag).filter_by(path="rh").count() == 1


def test_register_document_dedup_e_substituicao(db, seed):
    org = seed["ong"]
    doc, reason = register_document(db, org, "ferias.md", b"conteudo v1")
    db.commit()
    assert reason == "criado" and doc.status == "pending"
    assert Path(pipeline.upload_root() / org.slug).exists()

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
    doc, _ = register_document(db, org, "ferias.md", "político de férias " * 400)
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


def test_delete_document_limpa_tudo(db, seed, monkeypatch):
    org = seed["ong"]
    monkeypatch.setattr("app.kb.classify.classify_document", lambda *a, **k: [])
    doc, _ = register_document(db, org, "x.md", b"algum conteudo aqui")
    db.commit()
    process_document(db, doc.id)
    stored = Path(pipeline.upload_root().parent / doc.stored_path) \
        if not Path(doc.stored_path).is_absolute() else Path(doc.stored_path)
    delete_document(db, doc)
    db.commit()
    assert db.query(Document).count() == 0
    assert db.query(DocumentChunk).count() == 0
    assert not stored.exists()
```

Nota: `register_document` aceita `str` no teste de indexação — o código converte com `.encode("utf-8")` quando receber `str` (conveniência usada também pelo comando de pasta).

Rodar → FAIL.

- [ ] **Step 2: Implementar `pipeline.py`**

```python
"""Orquestração da ingestão: registrar, processar e remover documentos.

register_document e delete_document não commitam — quem chama controla a
transação. process_document commita e nunca levanta exceção: falha vira
status "error" no documento, visível na listagem do admin.
"""

import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy import delete, select

from ..anthropic_client import resolve_api_key
from ..config import SERVER_ROOT, settings
from ..models import (
    Document,
    DocumentChunk,
    DocumentTag,
    IngestJob,
    Organization,
    Tag,
)
from . import classify, embeddings
from .chunking import split_chunks
from .extract import ALLOWED_EXTENSIONS, extract_text

logger = logging.getLogger("teia.kb")


def upload_root() -> Path:
    configured = Path(settings.upload_dir)
    return configured if configured.is_absolute() else SERVER_ROOT / configured


def _stored_file(document: Document) -> Path:
    path = Path(document.stored_path)
    return path if path.is_absolute() else SERVER_ROOT / path


def ensure_tags(db, org_id: int, paths: List[str],
                status: str = "pending", source: str = "ia") -> List[Tag]:
    """Garante cada caminho e seus ancestrais; retorna as tags-folha."""
    leaves: List[Tag] = []
    for path in paths:
        parts = path.split("/")
        tag = None
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            tag = db.scalar(
                select(Tag).where(Tag.organization_id == org_id,
                                  Tag.path == prefix)
            )
            if tag is None:
                tag = Tag(organization_id=org_id, path=prefix,
                          status=status, source=source)
                db.add(tag)
                db.flush()
        if tag is not None:
            leaves.append(tag)
    return leaves


def register_document(db, org: Organization, filename: str,
                      data) -> Tuple[Optional[Document], str]:
    if isinstance(data, str):
        data = data.encode("utf-8")
    filename = Path(filename).name  # nunca confiar em caminho do cliente
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None, "formato"
    if not data or not data.strip():
        return None, "vazio"

    content_hash = hashlib.sha256(data).hexdigest()
    same_hash = db.scalar(
        select(Document).where(Document.organization_id == org.id,
                               Document.content_hash == content_hash)
    )
    if same_hash is not None:
        return None, "duplicado"

    reason = "criado"
    same_name = db.scalar(
        select(Document).where(Document.organization_id == org.id,
                               Document.filename == filename)
    )
    if same_name is not None:  # re-upload substitui a versão anterior
        delete_document(db, same_name)
        reason = "substituido"

    folder = upload_root() / org.slug
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{content_hash}{ext}"
    stored.write_bytes(data)
    stored_path = stored.as_posix()
    if not Path(settings.upload_dir).is_absolute():
        stored_path = stored.relative_to(SERVER_ROOT).as_posix()

    document = Document(
        organization_id=org.id, filename=filename, ext=ext,
        content_hash=content_hash, stored_path=stored_path,
    )
    db.add(document)
    db.flush()
    db.add(IngestJob(document_id=document.id))
    return document, reason


def delete_document(db, document: Document) -> None:
    db.execute(delete(DocumentChunk)
               .where(DocumentChunk.document_id == document.id))
    db.execute(delete(DocumentTag)
               .where(DocumentTag.document_id == document.id))
    db.execute(delete(IngestJob).where(IngestJob.document_id == document.id))
    try:
        _stored_file(document).unlink()
    except OSError:
        pass  # original já ausente não impede a remoção do registro
    db.delete(document)


def process_document(db, document_id: int) -> None:
    from . import search  # tardio: evita import circular

    document = db.get(Document, document_id)
    if document is None:
        return
    document.status = "processing"
    db.commit()
    try:
        text = extract_text(document.filename,
                            _stored_file(document).read_bytes())
        chunks = split_chunks(text)
        if not chunks:
            raise ValueError("Documento sem texto aproveitável.")

        org = db.get(Organization, document.organization_id)
        paths: List[str] = []
        api_key = resolve_api_key(org)
        if api_key:
            taxonomy = [
                t.path for t in db.scalars(
                    select(Tag).where(Tag.organization_id == org.id,
                                      Tag.status == "approved")
                ).all()
            ]
            try:
                paths = classify.classify_document(
                    api_key, taxonomy, document.filename, text)
            except Exception:  # classificação é opcional; indexa sem tags
                logger.exception("classificação falhou para doc %s", document.id)

        blobs: List[Optional[bytes]] = [None] * len(chunks)
        if embeddings.resolve_voyage_key():
            vectors = embeddings.embed_texts(chunks, "document")
            blobs = [embeddings.embedding_to_bytes(v) for v in vectors]

        db.execute(delete(DocumentChunk)
                   .where(DocumentChunk.document_id == document.id))
        db.execute(delete(DocumentTag)
                   .where(DocumentTag.document_id == document.id))
        for position, (chunk, blob) in enumerate(zip(chunks, blobs)):
            db.add(DocumentChunk(
                document_id=document.id, organization_id=document.organization_id,
                position=position, text=chunk, embedding=blob,
            ))
        for tag in ensure_tags(db, document.organization_id, paths):
            db.add(DocumentTag(document_id=document.id, tag_id=tag.id))
        document.chunk_count = len(chunks)
        document.status = "indexed"
        document.error = None
        db.commit()
    except Exception as exc:
        db.rollback()
        document = db.get(Document, document_id)
        document.status = "error"
        document.error = str(exc)[:500]
        db.commit()
    finally:
        search.invalidate(document.organization_id)
```

- [ ] **Step 3:** `search.invalidate` ainda não existe — criar um esqueleto mínimo `server/app/kb/search.py` nesta task para o pipeline importar:

```python
"""Busca híbrida (implementação completa na task seguinte)."""

_versions = {}
_cache = {}


def invalidate(org_id: int) -> None:
    _versions[org_id] = _versions.get(org_id, 0) + 1
    _cache.pop(org_id, None)


def reset_cache() -> None:
    _versions.clear()
    _cache.clear()
```

Descomentar no `clean_state` do conftest as linhas de `reset_cache()` (Task 1, Step 5).

- [ ] **Step 4: Rodar** `py -m pytest tests -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/kb/pipeline.py server/app/kb/search.py server/tests/test_kb_pipeline.py server/tests/conftest.py
git commit -m "feat: add ingestion pipeline with tag hierarchy and dedup"
```

---

### Task 6: Busca híbrida (`app/kb/search.py`)

**Files:**
- Modify: `server/app/kb/search.py` (substituir o esqueleto)
- Test: `server/tests/test_kb_search.py`

**Interfaces:**
- Produces: `@dataclass ChunkHit(chunk_id: int, document_id: int, filename: str, text: str, tags: List[str], score: float)`, `search_chunks(db, org_id: int, query: str, top_k: Optional[int] = None) -> List[ChunkHit]`, `invalidate(org_id)`, `reset_cache()`.

- [ ] **Step 1: Testes que falham**

Criar `server/tests/test_kb_search.py`:

```python
"""Busca híbrida: termos, vetores, bônus de tag e isolamento entre tenants."""

import pytest

from app.kb import pipeline, search
from app.kb.embeddings import embedding_to_bytes
from app.kb.search import search_chunks
from app.models import Document, DocumentChunk, DocumentTag, Tag

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
```

Rodar → FAIL.

- [ ] **Step 2: Implementar `search.py` (substituir o esqueleto)**

```python
"""Busca híbrida na base de conhecimento de um tenant.

Três sinais combinados:
- termos exatos: LIKE em SQL, sempre filtrado por organization_id;
- vetorial: cosseno (numpy) sobre a matriz de embeddings do tenant,
  cacheada em memória e invalidada a cada ingestão/remoção;
- tags: bônus quando termos da pergunta casam com tags aprovadas do
  documento.

Termos e vetores entram por Reciprocal Rank Fusion (RRF): robusto sem
calibrar pesos entre escalas de score diferentes. A interface é uma só —
trocar o motor (tsvector/pgvector na fase 2) não mexe em quem consome.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy import func, or_, select

from ..config import settings
from ..models import Document, DocumentChunk, DocumentTag, Tag
from . import embeddings

_RRF_K = 60          # constante clássica do RRF
_TAG_BONUS = 1.0 / 30  # ~2x o peso de um 1º lugar em um dos rankings
_LEX_LIMIT = 200     # candidatos lexicais por consulta
_VEC_LIMIT = 50      # candidatos vetoriais por consulta

_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "em",
    "no", "na", "nos", "nas", "por", "para", "com", "sem", "que", "qual",
    "quais", "como", "quando", "onde", "e", "ou", "se", "ao", "aos", "à",
    "às", "é", "são", "ser", "tem", "têm", "foi", "meu", "minha", "seu",
    "sua", "nosso", "nossa", "este", "esta", "isso", "esse", "essa", "sobre",
    "mais", "muito", "já", "não", "sim", "funciona", "funcionam",
}

_versions: Dict[int, int] = {}
_cache: Dict[int, Tuple[int, np.ndarray, Optional[np.ndarray]]] = {}


@dataclass
class ChunkHit:
    chunk_id: int
    document_id: int
    filename: str
    text: str
    tags: List[str]
    score: float


def invalidate(org_id: int) -> None:
    _versions[org_id] = _versions.get(org_id, 0) + 1
    _cache.pop(org_id, None)


def reset_cache() -> None:
    _versions.clear()
    _cache.clear()


def _terms(query: str) -> List[str]:
    tokens = re.findall(r"[0-9a-zA-Zà-öø-ÿÀ-ÖØ-ß-]+", query.lower())
    return [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS]


def _lexical_ranking(db, org_id: int, terms: List[str]) -> List[int]:
    """Ids de chunk ordenados por quantidade de termos casados."""
    conditions = [func.lower(DocumentChunk.text).like(f"%{t}%") for t in terms]
    rows = db.execute(
        select(DocumentChunk.id, DocumentChunk.text)
        .where(DocumentChunk.organization_id == org_id, or_(*conditions))
        .limit(_LEX_LIMIT)
    ).all()
    scored = []
    for chunk_id, text in rows:
        lowered = text.lower()
        matched = sum(1 for t in terms if t in lowered)
        scored.append((-matched, chunk_id))
    return [chunk_id for _, chunk_id in sorted(scored)]


def _org_matrix(db, org_id: int) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """(ids, matriz normalizada) dos chunks com embedding, com cache."""
    version = _versions.get(org_id, 0)
    cached = _cache.get(org_id)
    if cached and cached[0] == version:
        return cached[1], cached[2]
    rows = db.execute(
        select(DocumentChunk.id, DocumentChunk.embedding)
        .where(DocumentChunk.organization_id == org_id,
               DocumentChunk.embedding.isnot(None))
    ).all()
    if rows:
        ids = np.array([r[0] for r in rows], dtype=np.int64)
        matrix = embeddings.bytes_to_matrix([r[1] for r in rows])
    else:
        ids, matrix = np.empty(0, dtype=np.int64), None
    _cache[org_id] = (version, ids, matrix)
    return ids, matrix


def _vector_ranking(db, org_id: int, query: str) -> List[int]:
    if not embeddings.resolve_voyage_key():
        return []
    ids, matrix = _org_matrix(db, org_id)
    if matrix is None:
        return []
    try:
        query_vec = embeddings.embed_texts([query], "query")[0]
    except embeddings.EmbeddingError:
        return []  # busca segue só com termos e tags
    scores = embeddings.cosine_scores(matrix, query_vec)
    order = np.argsort(-scores)[:_VEC_LIMIT]
    return [int(ids[i]) for i in order]


def search_chunks(db, org_id: int, query: str,
                  top_k: Optional[int] = None) -> List[ChunkHit]:
    top_k = top_k or settings.kb_top_k
    terms = _terms(query)

    fused: Dict[int, float] = {}
    lexical = _lexical_ranking(db, org_id, terms) if terms else []
    for rank, chunk_id in enumerate(lexical):
        fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank)
    for rank, chunk_id in enumerate(_vector_ranking(db, org_id, query)):
        fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank)
    if not fused:
        return []

    rows = db.execute(
        select(DocumentChunk, Document.filename)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.id.in_(fused),
               DocumentChunk.organization_id == org_id)
    ).all()

    # tags aprovadas por documento (uma consulta para todos os candidatos)
    doc_ids = {chunk.document_id for chunk, _ in rows}
    doc_tags: Dict[int, List[str]] = {}
    if doc_ids:
        for document_id, path in db.execute(
            select(DocumentTag.document_id, Tag.path)
            .join(Tag, Tag.id == DocumentTag.tag_id)
            .where(DocumentTag.document_id.in_(doc_ids),
                   Tag.status == "approved",
                   Tag.organization_id == org_id)
        ).all():
            doc_tags.setdefault(document_id, []).append(path)

    hits: List[ChunkHit] = []
    for chunk, filename in rows:
        tags = doc_tags.get(chunk.document_id, [])
        score = fused[chunk.id]
        tag_words = {w for path in tags for w in re.split(r"[/-]", path)}
        if any(t in tag_words for t in terms):
            score += _TAG_BONUS
        hits.append(ChunkHit(
            chunk_id=chunk.id, document_id=chunk.document_id,
            filename=filename, text=chunk.text, tags=tags, score=score,
        ))
    hits.sort(key=lambda h: -h.score)
    return hits[:top_k]
```

- [ ] **Step 3: Rodar** `py -m pytest tests/test_kb_search.py tests/test_kb_pipeline.py -q` → PASS.

- [ ] **Step 4: Commit**

```bash
git add server/app/kb/search.py server/tests/test_kb_search.py
git commit -m "feat: add hybrid search (terms + vectors + tag boost, RRF)"
```

---

### Task 7: Integração no chat (`context_loader.py`, `routers/chat.py`)

**Files:**
- Modify: `server/app/context_loader.py`
- Modify: `server/app/routers/chat.py:94` (chamada de `build_system_blocks`)
- Test: `server/tests/test_kb_search.py` (acrescentar) — usa `fake_anthropic` do conftest

**Interfaces:**
- Produces: `build_system_blocks(org, db=None, query: Optional[str] = None) -> List[dict]` (retrocompatível: sem `db`/`query`, comportamento atual); `has_indexed_documents(db, org_id) -> bool`.

- [ ] **Step 1: Testes que falham** (acrescentar em `test_kb_search.py`)

```python
from tests.conftest import auth_headers, login


def _chat(client, token, text):
    return client.post("/api/chat", headers=auth_headers(token),
                       json={"messages": [{"role": "user", "content": text}]})


def test_chat_usa_retrieval_quando_ha_documentos(db, seed, client, fake_anthropic):
    org = seed["ong"]
    _add_doc(db, org.id, "orc.md", ["o orçamento anual foi aprovado"],
             embed=False)
    token = login(client, "maria@raizes.local", "senha-maria-123")
    res = _chat(client, token, "como ficou o orçamento?")
    assert res.status_code == 200
    kb_block = fake_anthropic[0]["system"][1]["text"]
    assert "orçamento anual" in kb_block
    assert "orc.md" in kb_block
    # modo retrieval: conteúdo varia por pergunta, não deve ter cache_control
    assert "cache_control" not in fake_anthropic[0]["system"][1]


def test_chat_sem_documentos_usa_pasta(db, seed, client, fake_anthropic):
    token = login(client, "maria@raizes.local", "senha-maria-123")
    res = _chat(client, token, "qual a missão de vocês?")
    assert res.status_code == 200
    kb_block = fake_anthropic[0]["system"][1]
    assert "sobre.md" in kb_block["text"]  # pasta examples-ong concatenada
    assert kb_block.get("cache_control") == {"type": "ephemeral"}
```

Rodar → FAIL.

- [ ] **Step 2: Implementar em `context_loader.py`**

Acrescentar imports e funções (manter `load_context` e `RULES` como estão):

```python
from sqlalchemy import func as sa_func
from sqlalchemy import select

from .models import Document
```

```python
def has_indexed_documents(db, org_id: int) -> bool:
    return bool(db.scalar(
        select(sa_func.count(Document.id)).where(
            Document.organization_id == org_id, Document.status == "indexed"
        )
    ))
```

Substituir `build_system_blocks` por:

```python
def build_system_blocks(org: Organization, db=None,
                        query: Optional[str] = None) -> List[dict]:
    """Blocos de system prompt: regras + base de conhecimento.

    Com documentos indexados, a base vira só os trechos relevantes para a
    pergunta (busca híbrida) — rápido e barato. Sem documentos indexados,
    mantém a pasta concatenada com cache (comportamento original).
    """
    intro = (
        f"Você é o assistente de chat da TeIA a serviço de: {org.name}.\n"
        f"Sua base de conhecimento cobre: {org.description}.\n"
        f"{RULES}"
    )
    if db is not None and query and has_indexed_documents(db, org.id):
        from .kb.search import search_chunks  # tardio: evita ciclo de import

        parts = []
        for hit in search_chunks(db, org.id, query):
            label = hit.filename + (f" · {', '.join(hit.tags)}" if hit.tags else "")
            parts.append(f"[{label}]\n{hit.text}")
        kb = "\n\n---\n\n".join(parts) or (
            "Nenhum trecho da base de conhecimento casou com esta pergunta."
        )
        kb = (
            "Trechos da base de conhecimento selecionados para a pergunta "
            "atual (cada um identificado por [arquivo · tags]):\n\n" + kb
        )
        # sem cache_control: o conteúdo muda a cada pergunta
        return [
            {"type": "text", "text": intro},
            {"type": "text", "text": f"<base_de_conhecimento>\n{kb}\n</base_de_conhecimento>"},
        ]
    kb = load_context(org.context_dir)
    return [
        {"type": "text", "text": intro},
        {
            "type": "text",
            "text": f"<base_de_conhecimento>\n{kb}\n</base_de_conhecimento>",
            "cache_control": {"type": "ephemeral"},
        },
    ]
```

- [ ] **Step 3: `chat.py`** — na linha da chamada, trocar por:

```python
        reply, usage, latency_ms = send_message(
            api_key,
            build_system_blocks(org, db=db, query=body.messages[-1].content),
            messages,
        )
```

- [ ] **Step 4: Rodar** `py -m pytest tests -q` → PASS (incluindo test_chat.py antigo).

- [ ] **Step 5: Commit**

```bash
git add server/app/context_loader.py server/app/routers/chat.py server/tests/test_kb_search.py
git commit -m "feat: chat answers from retrieved chunks when tenant is indexed"
```

---

### Task 8: Worker de ingestão (`app/kb/worker.py`) e wiring no `main.py`

**Files:**
- Create: `server/app/kb/worker.py`
- Modify: `server/app/main.py` (startup + limite de corpo para upload)
- Test: `server/tests/test_kb_pipeline.py` (acrescentar)

**Interfaces:**
- Produces: `kick() -> None`, `start() -> None` (respeita `settings.kb_worker_enabled`), `process_pending() -> int` (processa a fila até esvaziar; retorna quantos jobs tratou).

- [ ] **Step 1: Teste que falha** (acrescentar em `test_kb_pipeline.py`)

O worker usa `SessionLocal` do app; nos testes, apontamos para a sessão de teste:

```python
def test_worker_processa_fila(db, seed, monkeypatch):
    from tests.conftest import TestingSession

    from app.kb import worker

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
```

Rodar → FAIL.

- [ ] **Step 2: Implementar `worker.py`**

```python
"""Worker de ingestão: thread única consumindo a fila ingest_jobs.

Sem Redis: a fila é uma tabela, o worker é uma thread daemon acordada por
kick() após cada upload (e a cada 10s, para retomar pendências de um
restart). Escala vertical simples; fila externa só se a demanda provar
necessidade.
"""

import logging
import threading

from sqlalchemy import select

from ..config import settings
from ..database import SessionLocal
from ..models import IngestJob
from .pipeline import process_document

logger = logging.getLogger("teia.kb")

_wake = threading.Event()
_started = False


def kick() -> None:
    _wake.set()


def process_pending() -> int:
    """Processa jobs pendentes até a fila esvaziar. Retorna o total tratado."""
    handled = 0
    while True:
        db = SessionLocal()
        try:
            job = db.scalars(
                select(IngestJob).where(IngestJob.status == "pending")
                .order_by(IngestJob.id).limit(1)
            ).first()
            if job is None:
                return handled
            job.status = "running"
            job.attempts += 1
            db.commit()
            try:
                process_document(db, job.document_id)  # nunca levanta
                job.status = "done"
                job.error = None
            except Exception as exc:  # cinto e suspensório
                job.status = "error"
                job.error = str(exc)[:500]
            db.commit()
            handled += 1
        finally:
            db.close()


def _loop() -> None:
    while True:
        try:
            process_pending()
        except Exception:
            logger.exception("worker de ingestão falhou; seguirá tentando")
        _wake.wait(timeout=10)
        _wake.clear()


def start() -> None:
    global _started
    if _started or not settings.kb_worker_enabled:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="kb-worker").start()
```

Nota: `process_pending` referencia `SessionLocal` como atributo do módulo (`worker.SessionLocal`) para o monkeypatch do teste funcionar — usar `SessionLocal()` direto como importado acima já atende (o teste patcha `worker.SessionLocal`).

- [ ] **Step 3: `main.py`** — duas mudanças:

No `BodySizeLimitMiddleware.dispatch`, trocar o corpo por:

```python
    async def dispatch(self, request: Request, call_next):
        limit = settings.max_body_bytes
        if request.url.path.startswith("/api/admin/documents"):
            limit = settings.kb_max_upload_bytes  # upload de documentos
        length = request.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > limit:
            return JSONResponse({"detail": "Requisição grande demais."}, status_code=413)
        return await call_next(request)
```

No `startup()`, acrescentar ao final:

```python
    from .kb import worker
    worker.start()
```

- [ ] **Step 4: Rodar** `py -m pytest tests -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/kb/worker.py server/app/main.py server/tests/test_kb_pipeline.py
git commit -m "feat: add ingestion worker thread and upload body-size carve-out"
```

---

### Task 9: Rotas admin de documentos, tags e busca (`routers/documents.py`)

**Files:**
- Create: `server/app/routers/documents.py`
- Modify: `server/app/main.py` (include_router)
- Test: `server/tests/test_kb_api.py`

**Interfaces:**
- Consumes: `pipeline.register_document/delete_document/ensure_tags`, `worker.kick`, `search.search_chunks`, `deps.require_admin`.
- Produces rotas (todas admin, escopadas ao tenant do admin logado):
  - `POST /api/admin/documents` (multipart `files`; .zip expandido em memória) → 202 `{"created": [...], "skipped": [{"filename", "reason"}]}`
  - `GET /api/admin/documents` → `{"documents": [{id, filename, status, chunk_count, tags, error, created_at}]}`
  - `DELETE /api/admin/documents/{id}` → 200
  - `GET /api/admin/tags` / `POST /api/admin/tags {path}` / `PATCH /api/admin/tags/{id} {status}`
  - `GET /api/admin/kb-search?q=` → `{"hits": [{filename, text, tags, score}]}`

- [ ] **Step 1: Testes que falham**

Criar `server/tests/test_kb_api.py`:

```python
"""Rotas admin da base de conhecimento: upload, listagem, tags e isolamento."""

import io
import zipfile

import pytest

from app.kb import worker
from app.models import Document, Tag, User
from app.security import hash_password
from tests.conftest import TestingSession, auth_headers, login


@pytest.fixture()
def ong_admin(db, seed):
    admin = User(email="chefe@raizes.local", role="admin",
                 organization_id=seed["ong"].id,
                 password_hash=hash_password("senha-chefe-123"))
    db.add(admin)
    db.commit()
    return admin


@pytest.fixture()
def ong_token(client, ong_admin):
    return login(client, "chefe@raizes.local", "senha-chefe-123")


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
    token = login(client, "maria@raizes.local", "senha-maria-123")
    res = client.get("/api/admin/documents", headers=auth_headers(token))
    assert res.status_code == 403


def test_isolamento_admin_de_outro_tenant(client, db, seed, ong_token):
    _upload(client, ong_token, "segredo.md", b"dados internos da ong")
    teia_token = login(client, "admin@teia.local", "senha-admin-123")
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
```

Rodar → FAIL (404 nas rotas).

- [ ] **Step 2: Implementar `routers/documents.py`**

```python
"""Rotas admin da base de conhecimento: documentos, taxonomia e busca.

Diferente das rotas de gestão global (admin.py), tudo aqui é escopado à
organização do admin logado: cada tenant gerencia apenas a própria base.
"""

import io
import zipfile
from typing import List, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..kb import worker
from ..kb.classify import normalize_path
from ..kb.pipeline import delete_document, ensure_tags, register_document
from ..kb.search import invalidate, search_chunks
from ..models import Document, DocumentTag, Tag, User

router = APIRouter(prefix="/api/admin", tags=["base-de-conhecimento"])

MAX_ZIP_ENTRIES = 500


def _zip_entries(data: bytes) -> List[Tuple[str, bytes]]:
    """Expande um .zip em memória (nome, bytes); nada é escrito no disco
    com o caminho do zip, então zip-slip não se aplica."""
    entries: List[Tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist()[:MAX_ZIP_ENTRIES]:
            if info.is_dir():
                continue
            entries.append((info.filename, zf.read(info)))
    return entries


@router.post("/documents", status_code=202)
async def upload_documents(files: List[UploadFile] = File(...),
                           admin: User = Depends(require_admin),
                           db: Session = Depends(get_db)):
    org = admin.organization
    created, skipped = [], []
    for upload in files:
        name = upload.filename or "arquivo"
        data = await upload.read()
        if name.lower().endswith(".zip"):
            try:
                entries = _zip_entries(data)
            except zipfile.BadZipFile:
                skipped.append({"filename": name, "reason": "zip-invalido"})
                continue
        else:
            entries = [(name, data)]
        for entry_name, entry_data in entries:
            document, reason = register_document(db, org, entry_name, entry_data)
            if document is None:
                skipped.append({"filename": entry_name.rsplit("/", 1)[-1],
                                "reason": reason})
            else:
                created.append(document.filename)
    db.commit()
    worker.kick()
    return {"created": created, "skipped": skipped}


@router.get("/documents")
def list_documents(admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    docs = db.scalars(
        select(Document).where(Document.organization_id == admin.organization_id)
        .order_by(Document.created_at.desc(), Document.id.desc())
    ).all()
    tag_rows = db.execute(
        select(DocumentTag.document_id, Tag.path)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(Tag.organization_id == admin.organization_id)
    ).all()
    tags_by_doc = {}
    for document_id, path in tag_rows:
        tags_by_doc.setdefault(document_id, []).append(path)
    return {"documents": [
        {
            "id": d.id, "filename": d.filename, "status": d.status,
            "chunk_count": d.chunk_count, "error": d.error,
            "tags": sorted(tags_by_doc.get(d.id, [])),
            "created_at": d.created_at.isoformat() + "Z",
        }
        for d in docs
    ]}


@router.delete("/documents/{document_id}")
def remove_document(document_id: int, admin: User = Depends(require_admin),
                    db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None or document.organization_id != admin.organization_id:
        raise HTTPException(404, "Documento não encontrado.")
    delete_document(db, document)
    db.commit()
    invalidate(admin.organization_id)
    return {"ok": True}


# ------------------------------------------------------------------ taxonomia
@router.get("/tags")
def list_tags(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    tags = db.scalars(
        select(Tag).where(Tag.organization_id == admin.organization_id)
        .order_by(Tag.path)
    ).all()
    return {"tags": [
        {"id": t.id, "path": t.path, "status": t.status, "source": t.source}
        for t in tags
    ]}


class CreateTagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str


@router.post("/tags", status_code=201)
def create_tag(body: CreateTagRequest, admin: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    path = normalize_path(body.path)
    if not path:
        raise HTTPException(422, "Caminho de tag inválido.")
    leaves = ensure_tags(db, admin.organization_id, [path],
                         status="approved", source="admin")
    db.commit()
    leaf = leaves[0]
    return {"id": leaf.id, "path": leaf.path, "status": leaf.status}


class UpdateTagRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


@router.patch("/tags/{tag_id}")
def update_tag(tag_id: int, body: UpdateTagRequest,
               admin: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    if body.status not in ("approved", "rejected"):
        raise HTTPException(422, "Status deve ser 'approved' ou 'rejected'.")
    tag = db.get(Tag, tag_id)
    if tag is None or tag.organization_id != admin.organization_id:
        raise HTTPException(404, "Tag não encontrada.")
    tag.status = body.status
    db.commit()
    return {"id": tag.id, "path": tag.path, "status": tag.status}


# ---------------------------------------------------------------------- busca
@router.get("/kb-search")
def kb_search(q: str, admin: User = Depends(require_admin),
              db: Session = Depends(get_db)):
    hits = search_chunks(db, admin.organization_id, q)
    return {"hits": [
        {"filename": h.filename, "text": h.text, "tags": h.tags,
         "score": round(h.score, 6)}
        for h in hits
    ]}
```

- [ ] **Step 3: `main.py`** — importar e registrar:

```python
from .routers import admin, auth, chat, documents
...
app.include_router(documents.router)
```

- [ ] **Step 4: Rodar** `py -m pytest tests -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app/routers/documents.py server/app/main.py server/tests/test_kb_api.py
git commit -m "feat: add admin routes for documents, taxonomy and kb search"
```

---

### Task 10: Comando de ingestão de pasta (`app/ingest.py`)

**Files:**
- Create: `server/app/ingest.py`
- Test: `server/tests/test_kb_api.py` (acrescentar)

**Interfaces:**
- Consumes: `pipeline.register_document`, `worker.process_pending`, `context_loader` (trava de path).
- Produces: `ingest_folder(db, org: Organization) -> dict` (contadores `{"criado": n, "duplicado": n, ...}`); CLI `py -m app.ingest <slug>`.

- [ ] **Step 1: Teste que falha** (acrescentar em `test_kb_api.py`)

```python
def test_ingest_folder_ingere_pasta_do_tenant(db, seed):
    from app.ingest import ingest_folder

    counts = ingest_folder(db, seed["ong"])  # examples-ong/*.md
    db.commit()
    assert counts["criado"] == 3
    worker.process_pending()
    docs = db.query(Document).filter_by(organization_id=seed["ong"].id).all()
    assert {d.status for d in docs} == {"indexed"}
    # rodar de novo: tudo cai em duplicado
    counts = ingest_folder(db, seed["ong"])
    assert counts["criado"] == 0 and counts["duplicado"] == 3
```

Rodar → FAIL.

- [ ] **Step 2: Implementar `ingest.py`**

```python
"""Ingestão da pasta de contexto de um tenant pela linha de comando.

Uso (a partir de server/):  py -m app.ingest <slug-do-tenant>

Migração suave: os .md/.txt/.pdf da pasta context_dir do tenant entram no
mesmo pipeline do upload (tags, chunks, embeddings) e o chat passa a usar
retrieval em vez da pasta concatenada.
"""

import sys
from typing import Dict

from sqlalchemy import select

from .config import PROJECT_ROOT
from .database import SessionLocal
from .kb.extract import ALLOWED_EXTENSIONS
from .kb.pipeline import register_document
from .kb.worker import process_pending
from .models import Organization


def ingest_folder(db, org: Organization) -> Dict[str, int]:
    directory = (PROJECT_ROOT / org.context_dir).resolve()
    # mesma trava de segurança do context_loader
    if PROJECT_ROOT not in directory.parents and directory != PROJECT_ROOT:
        raise ValueError(f"context_dir fora do repositório: {org.context_dir}")
    counts: Dict[str, int] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        _, reason = register_document(db, org, path.name, path.read_bytes())
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: py -m app.ingest <slug-do-tenant>")
        return 2
    slug = sys.argv[1]
    db = SessionLocal()
    try:
        org = db.scalar(select(Organization).where(Organization.slug == slug))
        if org is None:
            print(f"Organização '{slug}' não encontrada.")
            return 1
        counts = ingest_folder(db, org)
        db.commit()
        print(f"Registrados: {counts}")
        handled = process_pending()
        print(f"Processados: {handled} documento(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Rodar** `py -m pytest tests -q` → PASS.

- [ ] **Step 4: Commit**

```bash
git add server/app/ingest.py server/tests/test_kb_api.py
git commit -m "feat: add folder ingestion command (py -m app.ingest <slug>)"
```

---

### Task 11: Documentação, verificação final e auditoria

**Files:**
- Modify: `README.md` (seção da base de conhecimento: upload, tags, VOYAGE_API_KEY, comando de ingestão)
- Modify: `docs/arquitetura-c4.md` (novos contêineres/componentes: fila, worker, busca)

- [ ] **Step 1:** Atualizar README: nova seção "Base de conhecimento indexada" cobrindo: como subir documentos (`POST /api/admin/documents`), formatos aceitos, `VOYAGE_API_KEY` opcional (sem ela a busca é só termos+tags), aprovação de tags, `py -m app.ingest <slug>`, e nota de custo (classificação Haiku + embeddings Voyage; consulta usa top-8 chunks). Registrar as dependências novas na lista justificada do README.
- [ ] **Step 2:** Atualizar `docs/arquitetura-c4.md` com o fluxo de ingestão e busca.
- [ ] **Step 3:** Suite completa: `py -m pytest tests -q` → tudo verde.
- [ ] **Step 4:** Rodar o agente `auditor-de-isolamento` sobre as mudanças; corrigir apontamentos confirmados.
- [ ] **Step 5:** Commit final:

```bash
git add README.md docs/arquitetura-c4.md
git commit -m "docs: document indexed knowledge base and update C4 architecture"
```
