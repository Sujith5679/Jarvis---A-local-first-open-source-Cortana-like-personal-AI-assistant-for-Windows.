"""Cross-encoder reranking — a precision pass over the hybrid retriever's
fused candidates (spec.md §16; this is the module `rag/hybrid_retriever.py`
was originally designed to slot in without callers changing).

Hybrid fusion (rag/hybrid_retriever.py) combines BM25 and cosine-similarity
scores that were each computed *independently* of the other side, then
linearly combined with fixed weights — a cheap, reasonable first pass, but
neither score was ever computed jointly against the query. A cross-encoder
reads the (query, passage) pair together through one transformer and outputs
a single relevance score, which is why cross-encoders reliably beat
bi-encoder/keyword fusion on precision@top-k. That accuracy costs more
compute per pair, so it only makes sense to run over a small candidate pool
(rag/hybrid_retriever.py's `rerank_candidate_pool`), not the whole index —
FAISS/FTS5 still do the cheap job of narrowing millions of chunks down to a
few dozen; the cross-encoder just re-orders that short list.

Runs fully offline (spec.md §33), same as rag/embeddings.py — the model is
~80MB and, like the embedding model, is loaded once per process and shared.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Protocol

from config.defaults import DEFAULT_RERANKER_MODEL


class Reranker(Protocol):
    def rerank(self, query: str, passages: list[str]) -> list[float]:
        """Return one relevance score per passage, same order as `passages`,
        in [0, 1] (higher = more relevant) - same scale as the hybrid
        retriever's fusion score, so callers/tool output can treat either
        one as "the" score without a units mismatch."""
        ...


class CrossEncoderReranker:
    """Local, offline cross-encoder reranker via sentence-transformers."""

    def __init__(self, model_name: str = DEFAULT_RERANKER_MODEL) -> None:
        # Imported lazily, same reasoning as rag/embeddings.py's
        # SentenceTransformer import: pulls in torch, slow to import and
        # unnecessary for anything that doesn't rerank.
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self._model = CrossEncoder(model_name)

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        pairs = [[query, passage] for passage in passages]
        raw_scores = self._model.predict(pairs)
        # ms-marco-MiniLM-L-6-v2 is trained with a binary cross-entropy
        # objective, so its raw output is a logit, not a bounded score -
        # sigmoid maps it to a (0, 1) relevance value (order-preserving, so
        # ranking is unaffected) that's on the same scale as the fusion
        # score instead of an unbounded, sign-ambiguous number.
        return [1.0 / (1.0 + math.exp(-float(s))) for s in raw_scores]


@lru_cache(maxsize=1)
def get_default_reranker() -> CrossEncoderReranker:
    """Process-wide cached model instance — loading it is not free (model
    weights + torch init), mirrors rag/embeddings.py's
    get_default_embedding_provider()."""
    return CrossEncoderReranker()
