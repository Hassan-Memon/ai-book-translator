"""Per-model price table (USD per 1M tokens), used to fill ``llm_call.cost_usd``.

Snapshot taken 2026-11-02 from public list prices; keep it honest and dated.
Unknown models cost 0 and are reported as such in the stats endpoint, which is
better than a silently wrong number. GitHub Models' free tier bills nothing,
but we still estimate at the upstream list price so the cost table reflects
what the same run would cost on a paid endpoint.
"""

from __future__ import annotations

# model substring -> (input $/1M, output $/1M)
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "claude-haiku": (1.00, 5.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-opus": (15.00, 75.00),
    "claude-fable": (15.00, 75.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "mistral-large": (2.00, 6.00),
    "mistral-small": (0.10, 0.30),
    "llama-3.3-70b": (0.59, 0.79),
    "text-embedding-3-small": (0.02, 0.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    model_l = model.lower()
    # Longest matching key wins so "gpt-4.1-mini" is not priced as "gpt-4.1".
    for key in sorted(PRICES, key=len, reverse=True):
        if key in model_l:
            inp, out = PRICES[key]
            return round((input_tokens * inp + output_tokens * out) / 1_000_000, 6)
    return 0.0
