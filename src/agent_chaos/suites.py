from __future__ import annotations

from importlib import resources
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import yaml

SUITE_ENTRY_POINT_GROUPS = ("toolgauntlet.suites", "agent_chaos.suites")


def built_in_suites_root() -> Path:
    package_root = resources.files("agent_chaos")
    return Path(str(package_root / "suites"))


def _suite_name_from_yaml(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except Exception:
        return path.parent.name
    suite = payload.get("suite") if isinstance(payload, dict) else {}
    if isinstance(suite, dict):
        return str(suite.get("name") or suite.get("id") or path.parent.name)
    return path.parent.name


def list_builtin_suites() -> list[dict[str, Any]]:
    root = built_in_suites_root()
    output: list[dict[str, Any]] = []
    if not root.exists():
        return output
    for suite_yaml in sorted(root.glob("*/suite.yaml")):
        output.append(
            {
                "id": suite_yaml.parent.name,
                "name": _suite_name_from_yaml(suite_yaml),
                "path": str(suite_yaml),
                "source": "builtin",
            }
        )
    return output


def list_plugin_suites() -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for group in SUITE_ENTRY_POINT_GROUPS:
        try:
            points = entry_points(group=group)
        except TypeError:
            points = entry_points().get(group, [])

        for point in points:
            try:
                loaded = point.load()
            except Exception:
                continue

            suite_path = None
            if callable(loaded):
                try:
                    suite_path = loaded()
                except Exception:
                    suite_path = None
            elif isinstance(loaded, str):
                suite_path = loaded

            identity = (point.name, str(suite_path))
            if suite_path and identity not in seen:
                seen.add(identity)
                output.append(
                    {
                        "id": point.name,
                        "name": point.name,
                        "path": str(suite_path),
                        "source": "plugin",
                    }
                )
    return output


def list_suites() -> list[dict[str, Any]]:
    return list_builtin_suites() + list_plugin_suites()


def resolve_suite_identifier(value: str) -> str:
    candidate = Path(value)
    if candidate.exists():
        return str(candidate)

    matches = [suite for suite in list_suites() if suite["id"] == value]
    if not matches:
        raise FileNotFoundError(f"Suite '{value}' not found")
    return matches[0]["path"]
