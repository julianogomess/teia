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
