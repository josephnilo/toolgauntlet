from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def deep_copy(value: Any) -> Any:
    return deepcopy(value)


def ensure_suite_yaml_path(path: str | Path) -> Path:
    p = Path(path)
    if p.is_dir():
        p = p / "suite.yaml"
    return p
