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

_RRF_K = 60            # constante clássica do RRF
_TAG_BONUS = 1.0 / 30  # ~2x o peso de um 1º lugar em um dos rankings
_LEX_LIMIT = 200       # candidatos lexicais por consulta
_VEC_LIMIT = 50        # candidatos vetoriais por consulta

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
