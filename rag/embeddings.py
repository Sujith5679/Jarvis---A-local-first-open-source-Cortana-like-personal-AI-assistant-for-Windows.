"""Pluggable embedding provider (spec.md §16, §33).

Embeddings must work fully offline — no cloud call is made just to index or
search your own files. The interface is provider-agnostic so a different
local model (or, later, a configured remote embedding API for users who
explicitly opt in) can be swapped in without touching `vector_store.py` or
`hybrid_retriever.py`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from config.defaults import DEFAULT_EMBEDDING_MODEL


class EmbeddingProvider(Protocol):
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalSentenceTransformerEmbeddings:
    """Local, offline embedding model via sentence-transformers."""

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        # Imported lazily: sentence-transformers pulls in torch, which is
        # slow to import and unnecessary for anything that doesn't touch RAG.
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        get_dimension = getattr(
            self._model, "get_embedding_dimension", self._model.get_sentence_embedding_dimension
        )
        self.dimension = get_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()


@lru_cache(maxsize=1)
def get_default_embedding_provider() -> LocalSentenceTransformerEmbeddings:
    """Process-wide cached embedding model instance — loading it is not free
    (model weights + torch init), so every caller should share one."""
    return LocalSentenceTransformerEmbeddings()
