from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .exceptions import SuiteLoadError
from .models import (
    ChaosSpec,
    InjectorSpec,
    SuccessSignal,
    SuiteDefinition,
    SuiteTask,
    SuiteTool,
    TaskExpected,
)
from .utils import ensure_suite_yaml_path


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise SuiteLoadError(f"Suite file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise SuiteLoadError(f"Invalid YAML in suite file: {path}") from exc
    if not isinstance(data, dict):
        raise SuiteLoadError(f"Suite YAML must be a mapping: {path}")
    return data


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise SuiteLoadError(f"Schema file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SuiteLoadError(f"Invalid JSON schema file: {path}") from exc
    if not isinstance(payload, dict):
        raise SuiteLoadError(f"Schema JSON must be an object: {path}")
    return payload


def _parse_success_signal(item: dict[str, Any]) -> SuccessSignal:
    if "type" not in item:
        raise SuiteLoadError("Success signal requires 'type'")
    return SuccessSignal(type=str(item["type"]), tool=item.get("tool"), value=item.get("value"))


def _parse_task(task_payload: dict[str, Any]) -> SuiteTask:
    try:
        task_id = str(task_payload["id"])
        prompt = str(task_payload["prompt"])
    except KeyError as exc:
        raise SuiteLoadError(f"Task missing required key: {exc}") from exc

    expected_payload = task_payload.get("expected") or {}
    if not isinstance(expected_payload, dict):
        raise SuiteLoadError(f"Task expected block must be a mapping: task={task_id}")

    success_signals = [
        _parse_success_signal(signal)
        for signal in expected_payload.get("success_signals", [])
        if isinstance(signal, dict)
    ]

    expected = TaskExpected(
        must_call_tools=[str(name) for name in expected_payload.get("must_call_tools", [])],
        constraints=[str(rule) for rule in expected_payload.get("constraints", [])],
        success_signals=success_signals,
    )
    return SuiteTask(id=task_id, prompt=prompt, expected=expected)


def _load_fixtures(root: Path, fixtures_value: Any) -> dict[str, Any]:
    if fixtures_value is None:
        return {}
    if isinstance(fixtures_value, dict):
        return fixtures_value
    if isinstance(fixtures_value, str):
        fixture_path = (root / fixtures_value).resolve()
        if fixture_path.suffix in {".yaml", ".yml"}:
            payload = _load_yaml(fixture_path)
        else:
            payload = _load_json(fixture_path)
        if not isinstance(payload, dict):
            raise SuiteLoadError("Fixture file must define an object mapping tool names to payloads")
        return payload
    raise SuiteLoadError("fixtures must be a mapping or a relative fixture file path")


def load_suite(suite_path: str | Path) -> SuiteDefinition:
    suite_yaml_path = ensure_suite_yaml_path(suite_path)
    raw = _load_yaml(suite_yaml_path)

    suite_block = raw.get("suite")
    if not isinstance(suite_block, dict):
        raise SuiteLoadError("suite.yaml requires a top-level 'suite' mapping")

    missing = [key for key in ("id", "name", "version") if key not in suite_block]
    if missing:
        raise SuiteLoadError(f"Suite metadata missing required keys: {', '.join(missing)}")

    root = suite_yaml_path.parent.resolve()

    tools_payload = raw.get("tools", [])
    tools: dict[str, SuiteTool] = {}
    for tool in tools_payload:
        if not isinstance(tool, dict):
            raise SuiteLoadError("Each tool entry must be a mapping")
        name = str(tool.get("name", "")).strip()
        schema_rel = str(tool.get("schema", "")).strip()
        if not name or not schema_rel:
            raise SuiteLoadError("Each tool requires name and schema")
        schema_path = (root / schema_rel).resolve()
        tools[name] = SuiteTool(name=name, schema_path=schema_path, schema=_load_json(schema_path))

    tasks_payload = raw.get("tasks", [])
    if not tasks_payload:
        raise SuiteLoadError("Suite must define at least one task")
    tasks = [_parse_task(task) for task in tasks_payload if isinstance(task, dict)]

    chaos_payload = raw.get("chaos") or {}
    chaos_seed = int(chaos_payload.get("seed", 0))
    injector_specs: list[InjectorSpec] = []
    for injector in chaos_payload.get("injectors", []):
        if not isinstance(injector, dict) or "type" not in injector:
            raise SuiteLoadError("Each chaos injector must be a mapping with type")
        injector_type = str(injector["type"])
        probability = float(injector.get("probability", 0.0))
        config = {k: v for k, v in injector.items() if k not in {"type", "probability"}}
        injector_specs.append(InjectorSpec(type=injector_type, probability=probability, config=config))

    fixtures = _load_fixtures(root, raw.get("fixtures"))

    return SuiteDefinition(
        suite_id=str(suite_block["id"]),
        name=str(suite_block["name"]),
        description=str(suite_block.get("description", "")),
        version=int(suite_block["version"]),
        root=root,
        tools=tools,
        tasks=tasks,
        chaos=ChaosSpec(seed=chaos_seed, injectors=injector_specs),
        fixtures=fixtures,
    )
