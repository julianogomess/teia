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
