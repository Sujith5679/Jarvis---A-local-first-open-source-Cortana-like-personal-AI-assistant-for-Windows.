"""Per-model USD pricing, for turning `llm.base.TokenUsage` into a cost
estimate (storage/repositories/usage.py).

Groq bills per token — live-verified against console.groq.com's pricing
page (Aug 2026). Ollama Cloud bills a flat monthly subscription (Free/Pro/
Max) by GPU-time, not by token, so there is no honest per-token price to
assign it: `estimate_cost_usd()` returns None for any (provider, model) not
listed here rather than fabricate a number, and callers must treat None as
"not applicable", not "free" or "zero".

Re-verify these numbers periodically (e.g. before relying on this for a
real budget decision) — provider pricing changes without notice and this
file will silently go stale otherwise.
"""

from __future__ import annotations

from llm.base import TokenUsage

# (provider, model) -> (price per 1M prompt tokens, price per 1M completion
# tokens), USD. Live-verified against console.groq.com/docs/model/openai/
# gpt-oss-120b, Aug 2026.
MODEL_PRICING_PER_MILLION_TOKENS: dict[tuple[str, str], tuple[float, float]] = {
    ("groq", "openai/gpt-oss-120b"): (0.15, 0.60),
}


def estimate_cost_usd(provider: str, model: str, usage: TokenUsage) -> float | None:
    """Returns the estimated USD cost of one call, or None if `provider`/
    `model` has no known per-token price (e.g. Ollama Cloud's subscription
    billing) — never a fabricated figure."""
    pricing = MODEL_PRICING_PER_MILLION_TOKENS.get((provider, model))
    if pricing is None:
        return None
    prompt_price, completion_price = pricing
    return (
        usage.prompt_tokens / 1_000_000 * prompt_price
        + usage.completion_tokens / 1_000_000 * completion_price
    )
