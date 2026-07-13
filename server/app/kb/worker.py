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
