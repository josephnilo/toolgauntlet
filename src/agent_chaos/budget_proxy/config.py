from __future__ import annotations

import os
from pathlib import Path

from .types import ProxyConfig


def _as_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_config(
    *,
    policy_path: str | None = None,
    audit_log_path: str | None = None,
    ledger_path: str | None = None,
    upstream_base_url: str | None = None,
    upstream_api_key: str | None = None,
    proxy_api_key: str | None = None,
    metric_namespace: str | None = None,
    rate_limiter_backend: str | None = None,
    redis_url: str | None = None,
    redis_key_prefix: str | None = None,
    otel_enabled: bool | None = None,
    otel_metrics_enabled: bool | None = None,
    otel_service_name: str | None = None,
    otel_endpoint: str | None = None,
    timeout_seconds: float | None = None,
    host: str | None = None,
    port: int | None = None,
) -> ProxyConfig:
    default_policy = os.environ.get("BUDGET_POLICY_PATH", "examples/budget_proxy/policy.example.yaml")
    default_audit = os.environ.get("BUDGET_AUDIT_LOG_PATH", "logs/budget-proxy-audit.jsonl")
    default_ledger = os.environ.get("BUDGET_LEDGER_PATH")

    cfg = ProxyConfig(
        upstream_base_url=(
            upstream_base_url
            or os.environ.get("BUDGET_UPSTREAM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com"
        ),
        upstream_api_key=(
            upstream_api_key
            or os.environ.get("BUDGET_UPSTREAM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        ),
        policy_path=str(Path(policy_path or default_policy)),
        audit_log_path=str(Path(audit_log_path or default_audit)),
        ledger_path=(ledger_path if ledger_path is not None else default_ledger),
        timeout_seconds=float(timeout_seconds or os.environ.get("BUDGET_TIMEOUT_SECONDS", 60.0)),
        host=host or os.environ.get("BUDGET_PROXY_HOST", "127.0.0.1"),
        port=int(port or os.environ.get("BUDGET_PROXY_PORT", 8080)),
        proxy_api_key=proxy_api_key or os.environ.get("BUDGET_PROXY_API_KEY"),
        project_header=os.environ.get("BUDGET_PROJECT_HEADER", "x-project-id"),
        project_api_key_header=os.environ.get("BUDGET_PROJECT_API_KEY_HEADER", "x-project-api-key"),
        metric_namespace=(
            metric_namespace
            or os.environ.get("BUDGET_METRIC_NAMESPACE")
            or "toolgauntlet_proxy"
        ),
        rate_limiter_backend=(
            rate_limiter_backend
            or os.environ.get("BUDGET_RATE_LIMIT_BACKEND")
            or "memory"
        ),
        redis_url=(
            redis_url
            or os.environ.get("BUDGET_REDIS_URL")
        ),
        redis_key_prefix=(
            redis_key_prefix
            or os.environ.get("BUDGET_REDIS_KEY_PREFIX")
            or "toolgauntlet_proxy_rl"
        ),
        otel_enabled=_as_bool(
            otel_enabled if otel_enabled is not None else os.environ.get("BUDGET_OTEL_ENABLED"),
            default=False,
        ),
        otel_metrics_enabled=_as_bool(
            otel_metrics_enabled if otel_metrics_enabled is not None else os.environ.get("BUDGET_OTEL_METRICS_ENABLED"),
            default=False,
        ),
        otel_service_name=(
            otel_service_name
            or os.environ.get("BUDGET_OTEL_SERVICE_NAME")
            or "toolgauntlet-proxy"
        ),
        otel_endpoint=(
            otel_endpoint
            or os.environ.get("BUDGET_OTEL_ENDPOINT")
        ),
    )
    return cfg
