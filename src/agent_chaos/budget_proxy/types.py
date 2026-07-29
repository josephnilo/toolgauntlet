from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelRate:
    prompt_per_1k_tokens: float
    completion_per_1k_tokens: float


@dataclass(slots=True)
class BudgetPolicy:
    allowed_models: list[str] = field(default_factory=list)
    blocked_models: list[str] = field(default_factory=list)
    max_input_chars: int = 20000
    max_output_tokens: int = 2048
    allow_stream: bool = True
    request_max_estimated_cost_usd: float | None = None
    monthly_budget_usd: dict[str, float] = field(default_factory=dict)
    requests_per_minute: dict[str, int] = field(default_factory=dict)
    project_api_keys: dict[str, list[str]] = field(default_factory=dict)
    model_rates: dict[str, ModelRate] = field(default_factory=dict)
    default_model_rate: ModelRate = field(default_factory=lambda: ModelRate(0.0, 0.0))
    safe_logging: bool = True
    redact_request_body: bool = True
    redact_response_body: bool = True


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    code: str
    message: str
    estimated_cost_usd: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UsageRecord:
    request_id: str
    project_id: str
    endpoint: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    status_code: int
    error: str | None = None


@dataclass(slots=True)
class ProxyConfig:
    upstream_base_url: str
    upstream_api_key: str | None
    policy_path: str
    audit_log_path: str
    ledger_path: str | None
    timeout_seconds: float = 60.0
    host: str = "127.0.0.1"
    port: int = 8080
    proxy_api_key: str | None = None
    project_header: str = "x-project-id"
    project_api_key_header: str = "x-project-api-key"
    metric_namespace: str = "toolgauntlet_proxy"
    rate_limiter_backend: str = "memory"
    redis_url: str | None = None
    redis_key_prefix: str = "toolgauntlet_proxy_rl"
    otel_enabled: bool = False
    otel_metrics_enabled: bool = False
    otel_service_name: str = "toolgauntlet-proxy"
    otel_endpoint: str | None = None
