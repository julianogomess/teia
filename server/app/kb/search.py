"""Busca híbrida na base de conhecimento (implementação completa em breve).

Por enquanto só o controle de cache/versão que o pipeline usa para
invalidar a matriz de embeddings de um tenant após ingestão/remoção.
"""

from typing import Dict

_versions: Dict[int, int] = {}
_cache: Dict[int, tuple] = {}


def invalidate(org_id: int) -> None:
    _versions[org_id] = _versions.get(org_id, 0) + 1
    _cache.pop(org_id, None)


def reset_cache() -> None:
    _versions.clear()
    _cache.clear()
