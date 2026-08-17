"""FAISS vector index (spec.md §16, §36).

Stored separately from SQLite but linked by a stable ID: a chunk's FAISS ID
is exactly its `document_chunks.id`, so no separate ID-mapping file is
needed — `VectorStore.search()` hands back the same integer IDs
`storage.repositories` uses everywhere else. Vectors are cosine similarity
via inner product on normalized embeddings (see `rag/embeddings.py`).
"""

from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np
from config.defaults import DEFAULT_TOP_K_VECTOR


class VectorStore:
    def __init__(self, dimension: int, index_path: Path) -> None:
        self.dimension = dimension
        self.index_path = index_path
        self._index = self._load_or_create()

    def _load_or_create(self) -> faiss.Index:
        if self.index_path.exists():
            index = faiss.read_index(str(self.index_path))
            if index.d != self.dimension:
                raise ValueError(
                    f"Vector index at {self.index_path} has dimension {index.d}, "
                    f"expected {self.dimension} (embedding model mismatch — reindex needed)"
                )
            return index
        base = faiss.IndexFlatIP(self.dimension)
        return faiss.IndexIDMap2(base)

    @property
    def size(self) -> int:
        return int(self._index.ntotal)

    def add(self, ids: list[int], vectors: list[list[float]]) -> None:
        if not ids:
            return
        arr = np.asarray(vectors, dtype="float32")
        id_arr = np.asarray(ids, dtype="int64")
        self._index.add_with_ids(arr, id_arr)
        self.save()

    def remove(self, ids: list[int]) -> None:
        if not ids:
            return
        id_arr = np.asarray(ids, dtype="int64")
        self._index.remove_ids(id_arr)
        self.save()

    def search(
        self, vector: list[float], top_k: int = DEFAULT_TOP_K_VECTOR
    ) -> list[tuple[int, float]]:
        """Returns (chunk_id, similarity_score) pairs, higher score = more similar."""
        if self._index.ntotal == 0:
            return []
        arr = np.asarray([vector], dtype="float32")
        scores, ids = self._index.search(arr, min(top_k, self._index.ntotal))
        results: list[tuple[int, float]] = []
        for chunk_id, score in zip(ids[0], scores[0], strict=True):
            if chunk_id == -1:
                continue
            results.append((int(chunk_id), float(score)))
        return results

    def save(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self.index_path))


def get_default_vector_store(dimension: int, index_path: Path | None = None) -> VectorStore:
    if index_path is None:
        from config.settings import get_settings

        index_path = get_settings().indexes_dir / "vectors.faiss"
    return VectorStore(dimension=dimension, index_path=index_path)
