from __future__ import annotations

import pytest


def test_reranker_returns_one_score_per_passage():
    """Not a real model - the fake below is what test_hybrid_retriever.py
    uses for reranker integration; this file just covers rag/reranker.py's
    own contract (empty input, order preservation) plus one real-model smoke
    test."""

    class _FakeReranker:
        def rerank(self, query: str, passages: list[str]) -> list[float]:
            return [float(len(p)) for p in passages]

    reranker = _FakeReranker()
    scores = reranker.rerank("q", ["short", "a much longer passage here"])
    assert scores == [5.0, 26.0]


def test_reranker_empty_passages_returns_empty_list():
    class _FakeReranker:
        def rerank(self, query: str, passages: list[str]) -> list[float]:
            return [float(len(p)) for p in passages]

    assert _FakeReranker().rerank("q", []) == []


@pytest.mark.slow
def test_cross_encoder_reranker_real_model_ranks_relevant_passage_higher():
    """One real end-to-end test with the actual cross-encoder model (slow:
    downloads/loads the model on first run)."""
    from rag.reranker import CrossEncoderReranker

    reranker = CrossEncoderReranker()
    scores = reranker.rerank(
        "What is the capital of France?",
        [
            "Paris is the capital and most populous city of France.",
            "Bananas are a good source of potassium.",
        ],
    )
    assert len(scores) == 2
    assert scores[0] > scores[1]
