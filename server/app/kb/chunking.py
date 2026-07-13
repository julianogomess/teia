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
