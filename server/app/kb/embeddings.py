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
