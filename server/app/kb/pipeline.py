"""Orquestração da ingestão: registrar, processar e remover documentos.

register_document e delete_document não commitam — quem chama controla a
transação. process_document commita e nunca levanta exceção: falha vira
status "error" no documento, visível na listagem do admin.
"""

import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Union

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
        if tag is not None and tag not in leaves:
            leaves.append(tag)
    return leaves


def register_document(db, org: Organization, filename: str,
                      data: Union[bytes, str]) -> Tuple[Optional[Document], str]:
    if isinstance(data, str):
        data = data.encode("utf-8")
    filename = Path(filename.replace("\\", "/")).name  # nunca confiar em caminho do cliente
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
                document_id=document.id,
                organization_id=document.organization_id,
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
