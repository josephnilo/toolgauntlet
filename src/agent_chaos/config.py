from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SuiteConfig:
    runs: int = 1
    concurrency: int = 1
    seed: int | None = None
    safe_logging: bool = True
    prompt_excerpt_chars: int = 120
    output_excerpt_chars: int = 200
    max_retries: int = 3
    retry_storm_threshold: int = 5
    retry_backoff_min_ms: int = 50
    latency_p95_target_ms: int = 2500
    regression_tolerance: float = 0.0
    otel_enabled: bool = False
    otel_metrics_enabled: bool = False
    otel_service_name: str = "toolgauntlet-runner"
    otel_endpoint: str | None = None
