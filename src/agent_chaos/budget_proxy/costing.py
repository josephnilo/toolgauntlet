from __future__ import annotations

from typing import Any

from .enforcement import estimate_cost_usd
from .types import BudgetPolicy


def usage_from_response(payload: dict[str, Any]) -> tuple[int, int]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return 0, 0

    prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0))
    completion = usage.get("completion_tokens", usage.get("output_tokens", 0))
    try:
        prompt_tokens = max(0, int(prompt))
    except (TypeError, ValueError):
        prompt_tokens = 0
    try:
        completion_tokens = max(0, int(completion))
    except (TypeError, ValueError):
        completion_tokens = 0
    return prompt_tokens, completion_tokens


def response_cost_usd(model: str, payload: dict[str, Any], policy: BudgetPolicy, fallback_estimated_cost_usd: float) -> tuple[int, int, float]:
    prompt_tokens, completion_tokens = usage_from_response(payload)
    if prompt_tokens == 0 and completion_tokens == 0:
        return 0, 0, fallback_estimated_cost_usd

    actual = estimate_cost_usd(model, prompt_tokens, completion_tokens, policy)
    return prompt_tokens, completion_tokens, actual
