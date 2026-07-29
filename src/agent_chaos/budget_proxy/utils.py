from __future__ import annotations

import uuid
from typing import Any


def request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def coerce_json(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Request body must be a JSON object")
    return value
