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
