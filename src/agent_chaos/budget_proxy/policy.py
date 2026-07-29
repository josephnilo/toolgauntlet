from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .types import BudgetPolicy, ModelRate


class PolicyLoadError(ValueError):
    """Raised when a proxy policy is invalid."""


def _as_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PolicyLoadError(f"{field_name} must be numeric") from exc
    if number < 0:
        raise PolicyLoadError(f"{field_name} must be >= 0")
    return number


def _as_int(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyLoadError(f"{field_name} must be an integer") from exc
    if number < 0:
        raise PolicyLoadError(f"{field_name} must be >= 0")
    return number


def _load_rate(payload: dict[str, Any], field_name: str) -> ModelRate:
    if not isinstance(payload, dict):
        raise PolicyLoadError(f"{field_name} must be a mapping")
    prompt_rate = _as_float(payload.get("prompt_per_1k_tokens", 0.0), f"{field_name}.prompt_per_1k_tokens")
    completion_rate = _as_float(
        payload.get("completion_per_1k_tokens", 0.0),
        f"{field_name}.completion_per_1k_tokens",
    )
    return ModelRate(prompt_per_1k_tokens=prompt_rate, completion_per_1k_tokens=completion_rate)


def _load_int_mapping(raw: Any, field_name: str) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PolicyLoadError(f"{field_name} must be a mapping")
    return {
        str(key): _as_int(value, f"{field_name}.{key}")
        for key, value in raw.items()
    }


def _load_project_api_keys(raw: Any) -> dict[str, list[str]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PolicyLoadError("project_api_keys must be a mapping")
    output: dict[str, list[str]] = {}
    for project, values in raw.items():
        if not isinstance(values, list):
            raise PolicyLoadError(f"project_api_keys.{project} must be a list of strings")
        keys = [str(item) for item in values if str(item)]
        if keys:
            output[str(project)] = keys
    return output


def load_policy(path: str | Path) -> BudgetPolicy:
    policy_path = Path(path)
    if not policy_path.exists():
        raise PolicyLoadError(f"Policy file not found: {policy_path}")

    try:
        with policy_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise PolicyLoadError(f"Invalid YAML: {policy_path}") from exc

    if not isinstance(raw, dict):
        raise PolicyLoadError("Policy file must contain a YAML object")

    allowed_models_raw = raw.get("allowed_models", [])
    blocked_models_raw = raw.get("blocked_models", [])
    if not isinstance(allowed_models_raw, list):
        raise PolicyLoadError("allowed_models must be a list")
    if not isinstance(blocked_models_raw, list):
        raise PolicyLoadError("blocked_models must be a list")

    monthly_budget_raw = raw.get("monthly_budget_usd", {})
    if monthly_budget_raw is None:
        monthly_budget_raw = {}
    if not isinstance(monthly_budget_raw, dict):
        raise PolicyLoadError("monthly_budget_usd must be a mapping")
    monthly_budget = {
        str(project): _as_float(value, f"monthly_budget_usd.{project}")
        for project, value in monthly_budget_raw.items()
    }

    requests_per_minute = _load_int_mapping(raw.get("requests_per_minute", {}), "requests_per_minute")
    project_api_keys = _load_project_api_keys(raw.get("project_api_keys", {}))

    model_rates_raw = raw.get("model_rates", {})
    if not isinstance(model_rates_raw, dict):
        raise PolicyLoadError("model_rates must be a mapping")
    model_rates = {
        str(model): _load_rate(rate_payload, f"model_rates.{model}")
        for model, rate_payload in model_rates_raw.items()
    }

    default_rate_raw = raw.get("default_model_rate", {})
    default_model_rate = _load_rate(default_rate_raw, "default_model_rate")

    request_cap = raw.get("request_max_estimated_cost_usd")
    request_max_estimated_cost_usd = (
        _as_float(request_cap, "request_max_estimated_cost_usd")
        if request_cap is not None
        else None
    )

    return BudgetPolicy(
        allowed_models=[str(item) for item in allowed_models_raw],
        blocked_models=[str(item) for item in blocked_models_raw],
        max_input_chars=_as_int(raw.get("max_input_chars", 20000), "max_input_chars"),
        max_output_tokens=_as_int(raw.get("max_output_tokens", 2048), "max_output_tokens"),
        allow_stream=bool(raw.get("allow_stream", True)),
        request_max_estimated_cost_usd=request_max_estimated_cost_usd,
        monthly_budget_usd=monthly_budget,
        requests_per_minute=requests_per_minute,
        project_api_keys=project_api_keys,
        model_rates=model_rates,
        default_model_rate=default_model_rate,
        safe_logging=bool(raw.get("safe_logging", True)),
        redact_request_body=bool(raw.get("redact_request_body", True)),
        redact_response_body=bool(raw.get("redact_response_body", True)),
    )
