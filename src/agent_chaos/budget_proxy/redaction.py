from __future__ import annotations

from typing import Any

from agent_chaos.redaction import redact_text


SENSITIVE_HEADERS = {
    "authorization",
    "x-api-key",
    "api-key",
    "cookie",
    "set-cookie",
}


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADERS:
            redacted[key] = "[REDACTED]"
        else:
            redacted[key] = redact_text(value)
    return redacted


def redact_payload(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, child in value.items():
            key_lower = key.lower()
            if any(marker in key_lower for marker in ("key", "token", "secret", "password", "authorization")):
                output[key] = "[REDACTED]"
            else:
                output[key] = redact_payload(child)
        return output
    return value
