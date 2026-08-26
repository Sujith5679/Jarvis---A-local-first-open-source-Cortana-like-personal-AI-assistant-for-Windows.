from __future__ import annotations

from llm.base import TokenUsage
from llm.pricing import estimate_cost_usd


def test_known_model_computes_cost():
    # Live-verified pricing (console.groq.com, Aug 2026): $0.15/1M prompt,
    # $0.60/1M completion for openai/gpt-oss-120b.
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000)
    cost = estimate_cost_usd("groq", "openai/gpt-oss-120b", usage)
    assert cost == 0.15 + 0.60


def test_partial_usage_scales_linearly():
    usage = TokenUsage(prompt_tokens=500_000, completion_tokens=0, total_tokens=500_000)
    cost = estimate_cost_usd("groq", "openai/gpt-oss-120b", usage)
    assert cost == 0.075


def test_unknown_model_returns_none_not_zero():
    # Ollama Cloud bills a flat GPU-time subscription, not per token - there
    # is no honest dollar figure to compute, so this must be None, never 0.0.
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=1000, total_tokens=2000)
    assert estimate_cost_usd("ollama_cloud", "gpt-oss:120b", usage) is None


def test_unknown_provider_returns_none():
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=1000, total_tokens=2000)
    assert estimate_cost_usd("some_future_provider", "some-model", usage) is None
