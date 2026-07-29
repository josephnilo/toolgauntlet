from __future__ import annotations

from typing import Any

from .types import BudgetPolicy, PolicyDecision


def extract_model(payload: dict[str, Any]) -> str:
    model = payload.get("model")
    return str(model or "")


def extract_max_output_tokens(payload: dict[str, Any]) -> int:
    for key in ("max_tokens", "max_output_tokens", "max_completion_tokens"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
    return 0


def estimate_input_chars(payload: dict[str, Any]) -> int:
    total = 0

    def visit(value: Any) -> None:
        nonlocal total
        if isinstance(value, str):
            total += len(value)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)

    if "messages" in payload:
        visit(payload.get("messages"))
    elif "input" in payload:
        visit(payload.get("input"))
    else:
        visit(payload)

    return total


def estimate_prompt_tokens(payload: dict[str, Any]) -> int:
    # Coarse deterministic estimate: ~4 characters per token.
    return max(1, estimate_input_chars(payload) // 4)


def estimate_completion_tokens(payload: dict[str, Any], policy: BudgetPolicy) -> int:
    requested = extract_max_output_tokens(payload)
    if requested <= 0:
        return min(policy.max_output_tokens, 256)
    return requested


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int, policy: BudgetPolicy) -> float:
    rate = policy.model_rates.get(model, policy.default_model_rate)
    prompt_cost = (prompt_tokens / 1000.0) * rate.prompt_per_1k_tokens
    completion_cost = (completion_tokens / 1000.0) * rate.completion_per_1k_tokens
    return round(prompt_cost + completion_cost, 8)


def enforce_request(
    payload: dict[str, Any],
    endpoint: str,
    project_id: str,
    policy: BudgetPolicy,
    current_month_spend_usd: float,
) -> PolicyDecision:
    model = extract_model(payload)
    if not model:
        return PolicyDecision(False, "missing_model", "Request must include a model")

    if policy.allowed_models and model not in policy.allowed_models:
        return PolicyDecision(False, "model_not_allowed", f"Model '{model}' is not allowed")

    if model in policy.blocked_models:
        return PolicyDecision(False, "model_blocked", f"Model '{model}' is blocked")

    if bool(payload.get("stream", False)) and not policy.allow_stream:
        return PolicyDecision(False, "stream_not_allowed", "Streaming is disabled by policy")

    max_tokens = extract_max_output_tokens(payload)
    if max_tokens > policy.max_output_tokens:
        return PolicyDecision(
            False,
            "max_output_tokens_exceeded",
            f"Requested output tokens {max_tokens} exceeds policy max {policy.max_output_tokens}",
            details={"requested": max_tokens, "max": policy.max_output_tokens},
        )

    input_chars = estimate_input_chars(payload)
    if input_chars > policy.max_input_chars:
        return PolicyDecision(
            False,
            "max_input_chars_exceeded",
            f"Input chars {input_chars} exceeds policy max {policy.max_input_chars}",
            details={"input_chars": input_chars, "max": policy.max_input_chars},
        )

    prompt_tokens = estimate_prompt_tokens(payload)
    completion_tokens = estimate_completion_tokens(payload, policy)
    estimated_cost = estimate_cost_usd(model, prompt_tokens, completion_tokens, policy)

    if policy.request_max_estimated_cost_usd is not None and estimated_cost > policy.request_max_estimated_cost_usd:
        return PolicyDecision(
            False,
            "request_cost_exceeded",
            f"Estimated cost ${estimated_cost:.6f} exceeds per-request limit ${policy.request_max_estimated_cost_usd:.6f}",
            estimated_cost_usd=estimated_cost,
        )

    budget_limit = policy.monthly_budget_usd.get(project_id)
    if budget_limit is None:
        budget_limit = policy.monthly_budget_usd.get("default")

    if budget_limit is not None and (current_month_spend_usd + estimated_cost) > budget_limit:
        return PolicyDecision(
            False,
            "monthly_budget_exceeded",
            (
                f"Projected monthly spend ${(current_month_spend_usd + estimated_cost):.6f} "
                f"exceeds budget ${budget_limit:.6f}"
            ),
            estimated_cost_usd=estimated_cost,
            details={
                "current_month_spend_usd": current_month_spend_usd,
                "budget_limit_usd": budget_limit,
            },
        )

    return PolicyDecision(
        True,
        "allowed",
        "Allowed",
        estimated_cost_usd=estimated_cost,
        details={
            "project_id": project_id,
            "endpoint": endpoint,
            "model": model,
            "estimated_prompt_tokens": prompt_tokens,
            "estimated_completion_tokens": completion_tokens,
        },
    )
