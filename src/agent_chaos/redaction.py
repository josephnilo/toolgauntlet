from __future__ import annotations

import os
import re
from typing import Any

_SECRET_TOKEN_PATTERN = re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b")
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{12,}")
_HEX_TOKEN_PATTERN = re.compile(r"\b[a-fA-F0-9]{32,}\b")


_ENV_SECRET_KEYS = tuple(
    key
    for key in os.environ
    if any(marker in key.upper() for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
)


def redact_text(value: str) -> str:
    redacted = _SECRET_TOKEN_PATTERN.sub("[REDACTED_TOKEN]", value)
    redacted = _BEARER_PATTERN.sub("Bearer [REDACTED_TOKEN]", redacted)
    redacted = _HEX_TOKEN_PATTERN.sub("[REDACTED_HEX]", redacted)

    # Redact known sensitive env var values if they leak into logs.
    for key in _ENV_SECRET_KEYS:
        env_value = os.environ.get(key)
        if not env_value:
            continue
        if len(env_value) < 6:
            continue
        redacted = redacted.replace(env_value, f"[REDACTED_{key}]")
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, child in value.items():
            key_upper = key.upper()
            is_usage_counter = key_upper.endswith("_TOKENS")
            if any(marker in key_upper for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and not is_usage_counter:
                output[key] = "[REDACTED]"
            else:
                output[key] = redact_value(child)
        return output
    return value
