from __future__ import annotations

import inspect
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from random import Random
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .config import SuiteConfig
from .injectors import build_pipeline
from .injectors.base import ToolCallContext
from .loader import load_suite
from .models import ChaosReport, RegressionComparison, TaskRunRecord, ToolCallRecord
from .redaction import redact_text, redact_value
from .scoring import build_score, evaluate_task_run
from .suites import resolve_suite_identifier
from .telemetry import build_telemetry
from .utils import json_dumps, stable_hash

AgentAdapter = Callable[[str, Callable[[str, dict[str, Any] | None], Any], dict[str, Any] | None], Any]
ToolMapping = dict[str, Callable[..., Any]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _excerpt(value: Any, limit: int) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json_dumps(value)
        except Exception:
            text = str(value)
    return text[:limit]


def _coerce_output(result: Any) -> tuple[str, dict[str, Any] | None]:
    if isinstance(result, str):
        return result, None
    if isinstance(result, dict):
        output = result.get("output")
        if output is None:
            output = result.get("text")
        if output is None:
            output = result.get("final")
        if output is None:
            output = str(result)
        return str(output), result.get("usage")
    if isinstance(result, tuple) and len(result) == 2:
        return str(result[0]), result[1] if isinstance(result[1], dict) else None
    return str(result), None


def _fixture_response(fixtures: dict[str, Any], tool_name: str, args: dict[str, Any], rnd: Random) -> Any:
    fixture = fixtures.get(tool_name)
    if fixture is None:
        return {"ok": True, "tool": tool_name, **args}

    if isinstance(fixture, list):
        if not fixture:
            return {"ok": True, "tool": tool_name, **args}
        return deepcopy(rnd.choice(fixture))

    if isinstance(fixture, dict):
        if "by_id" in fixture and isinstance(fixture["by_id"], dict):
            by_id = fixture["by_id"]
            identity = None
            for key in ("id", "order_id", "ticket_id", "trip_id", "booking_id", "reservation_id"):
                if key in args:
                    identity = str(args[key])
                    break
            if identity and identity in by_id:
                return deepcopy(by_id[identity])
            if "default" in by_id:
                return deepcopy(by_id["default"])
        if "response" in fixture:
            return deepcopy(fixture["response"])
        return deepcopy(fixture)

    return deepcopy(fixture)


def _invoke_tool_impl(tool_impl: Callable[..., Any], args: dict[str, Any], context: dict[str, Any]) -> Any:
    try:
        signature = inspect.signature(tool_impl)
        arg_count = len(
            [
                parameter
                for parameter in signature.parameters.values()
                if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
            ]
        )
    except (TypeError, ValueError):
        arg_count = 1

    if arg_count <= 1:
        return tool_impl(args)
    return tool_impl(args, context)


def _build_regression(current: ChaosReport, baseline: ChaosReport, tolerance: float) -> RegressionComparison:
    metric_names = [
        "task_success_rate",
        "schema_compliance_rate",
        "retry_hygiene_rate",
        "latency_score",
        "safety_score",
        "overall_score",
    ]
    metric_deltas = {
        name: getattr(current.score, name) - getattr(baseline.score, name)
        for name in metric_names
        if hasattr(baseline.score, name)
    }
    delta = current.score.overall_score - baseline.score.overall_score
    return RegressionComparison(
        baseline_score=baseline.score.overall_score,
        current_score=current.score.overall_score,
        delta=delta,
        regression=delta < (0.0 - tolerance),
        metric_deltas=metric_deltas,
    )


def run_suite(
    agent: AgentAdapter,
    suite_path: str | Path,
    config: SuiteConfig | None = None,
    tools: ToolMapping | None = None,
    baseline: ChaosReport | str | Path | None = None,
) -> ChaosReport:
    cfg = config or SuiteConfig()
    telemetry = build_telemetry(
        traces_enabled=cfg.otel_enabled,
        metrics_enabled=cfg.otel_metrics_enabled,
        service_name=cfg.otel_service_name,
        endpoint=cfg.otel_endpoint,
    )
    suite = load_suite(resolve_suite_identifier(str(suite_path)))
    validators = {name: Draft202012Validator(tool.schema) for name, tool in suite.tools.items()}

    base_seed = cfg.seed if cfg.seed is not None else suite.chaos.seed

    jobs: list[tuple[int, int, int]] = []
    for task_idx, _task in enumerate(suite.tasks):
        for run_index in range(cfg.runs):
            seed = base_seed + (task_idx * 100003) + (run_index * 9176)
            jobs.append((task_idx, run_index, seed))

    def execute_job(task_idx: int, run_index: int, seed: int) -> TaskRunRecord:
        task = suite.tasks[task_idx]
        run_random = Random(seed)
        pipeline = build_pipeline(
            [
                {"type": spec.type, "probability": spec.probability, "config": spec.config}
                for spec in suite.chaos.injectors
            ]
        )
        suite_state: dict[str, Any] = {}
        tool_calls: list[ToolCallRecord] = []
        attempts: dict[str, int] = {}

        prompt_redacted = redact_text(task.prompt)
        prompt_excerpt = (
            _excerpt(prompt_redacted, cfg.prompt_excerpt_chars)
            if cfg.safe_logging
            else prompt_redacted
        )

        run_started = time.perf_counter()

        def tool_executor(tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
            with telemetry.span(
                "toolgauntlet.tool_call",
                attributes={
                    "toolgauntlet.task_id": task.id,
                    "toolgauntlet.tool_name": tool_name,
                    "toolgauntlet.run_index": run_index,
                },
            ):
                if tool_name not in suite.tools:
                    raise ValueError(f"Unknown tool '{tool_name}' for suite {suite.suite_id}")

                args = arguments or {}
                args = deepcopy(args)
                attempt_key = f"{tool_name}|{json_dumps(args)}"
                attempts[attempt_key] = attempts.get(attempt_key, 0) + 1
                attempt = attempts[attempt_key]

                call_context = ToolCallContext(
                    task_id=task.id,
                    run_index=run_index,
                    tool_name=tool_name,
                    arguments=args,
                    random=run_random,
                    suite_state=suite_state,
                )
                started = time.perf_counter()
                output: Any | None = None
                output_excerpt: str | None = None
                error: str | None = None
                schema_compliant: bool | None = None

                try:
                    pipeline.before_call(call_context)

                    if tools and tool_name in tools:
                        output = _invoke_tool_impl(
                            tools[tool_name],
                            args,
                            {"task": task, "run_index": run_index, "seed": seed},
                        )
                    else:
                        output = _fixture_response(suite.fixtures, tool_name, args, run_random)

                    output = pipeline.after_call(call_context, output)
                    try:
                        validators[tool_name].validate(output)
                        schema_compliant = True
                    except Exception:
                        schema_compliant = False

                    output_excerpt = _excerpt(redact_value(output), cfg.output_excerpt_chars)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                finally:
                    finished = time.perf_counter()
                    latency_ms = round((finished - started) * 1000.0, 2)
                    tool_calls.append(
                        ToolCallRecord(
                            tool=tool_name,
                            arguments=redact_value(args),
                            output=redact_value(output),
                            output_excerpt=output_excerpt,
                            error=error,
                            latency_ms=latency_ms,
                            offset_ms=round((started - run_started) * 1000.0, 2),
                            timestamp=_now_iso(),
                            attempt=attempt,
                            schema_compliant=schema_compliant,
                            injector_events=call_context.events,
                        )
                    )
                    telemetry.record_counter(
                        "toolgauntlet.harness.tool_calls",
                        attributes={"suite_id": suite.suite_id, "task_id": task.id, "tool": tool_name},
                    )
                    if error:
                        telemetry.record_counter(
                            "toolgauntlet.harness.tool_errors",
                            attributes={"suite_id": suite.suite_id, "task_id": task.id, "tool": tool_name},
                        )
                    telemetry.record_histogram(
                        "toolgauntlet.harness.tool_latency_ms",
                        latency_ms,
                        unit="ms",
                        attributes={"suite_id": suite.suite_id, "task_id": task.id, "tool": tool_name},
                    )

                if error:
                    raise RuntimeError(error)
                return output

        output_text = ""
        output_excerpt = ""
        exception: str | None = None
        usage: dict[str, Any] | None = None

        try:
            with telemetry.span(
                "toolgauntlet.agent_call",
                attributes={
                    "toolgauntlet.task_id": task.id,
                    "toolgauntlet.run_index": run_index,
                    "toolgauntlet.suite_id": suite.suite_id,
                },
            ):
                result = agent(
                    task.prompt,
                    tool_executor,
                    {
                        "task_id": task.id,
                        "suite_id": suite.suite_id,
                        "constraints": task.expected.constraints,
                        "seed": seed,
                        "tools": [
                            {
                                "name": tool.name,
                                "schema": tool.schema,
                            }
                            for tool in suite.tools.values()
                        ],
                    },
                )
            output_text, usage = _coerce_output(result)
        except Exception as exc:
            exception = f"{type(exc).__name__}: {exc}"

        output_text = redact_text(output_text)
        output_excerpt = _excerpt(output_text, cfg.output_excerpt_chars)
        if cfg.safe_logging:
            stored_output_text = output_excerpt
        else:
            stored_output_text = output_text

        elapsed_ms = round((time.perf_counter() - run_started) * 1000.0, 2)
        success, tool_call_correct, failure_reasons, safety_violations, retry_summary = evaluate_task_run(
            task=task,
            output_text=output_text,
            tool_calls=tool_calls,
            exception=exception,
            config=cfg,
        )
        telemetry.record_counter(
            "toolgauntlet.harness.task_runs",
            attributes={"suite_id": suite.suite_id, "task_id": task.id},
        )
        telemetry.record_counter(
            "toolgauntlet.harness.task_run_outcomes",
            attributes={
                "suite_id": suite.suite_id,
                "task_id": task.id,
                "outcome": "success" if success else "failure",
            },
        )
        telemetry.record_histogram(
            "toolgauntlet.harness.task_latency_ms",
            elapsed_ms,
            unit="ms",
            attributes={"suite_id": suite.suite_id, "task_id": task.id},
        )

        return TaskRunRecord(
            task_id=task.id,
            run_index=run_index,
            seed=seed,
            prompt_hash=stable_hash(task.prompt),
            prompt_excerpt=prompt_excerpt,
            output_excerpt=output_excerpt,
            output_text=stored_output_text,
            tool_calls=tool_calls,
            latency_ms=elapsed_ms,
            success=success,
            tool_call_correct=tool_call_correct,
            failure_reasons=failure_reasons,
            safety_violations=safety_violations,
            retry_summary=retry_summary,
            exception=exception,
            usage=redact_value(usage) if usage else None,
        )

    task_runs: list[TaskRunRecord] = []
    worker_count = max(1, cfg.concurrency)

    if worker_count == 1:
        for task_idx, run_index, seed in jobs:
            task_runs.append(execute_job(task_idx, run_index, seed))
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(execute_job, task_idx, run_index, seed): (task_idx, run_index)
                for task_idx, run_index, seed in jobs
            }
            for future in as_completed(future_map):
                task_runs.append(future.result())

    task_runs.sort(key=lambda run: (run.task_id, run.run_index))

    score, metrics, per_task, top_failure_reasons = build_score(task_runs, cfg)

    # Optional provider usage aggregation.
    usage_entries = [run.usage for run in task_runs if run.usage]
    if usage_entries:
        prompt_tokens = sum(int(entry.get("prompt_tokens", 0)) for entry in usage_entries)
        completion_tokens = sum(int(entry.get("completion_tokens", 0)) for entry in usage_entries)
        cost_estimate = sum(float(entry.get("cost_usd", 0.0)) for entry in usage_entries)
        metrics["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost_estimate_usd": round(cost_estimate, 6) if cost_estimate else None,
        }

    report = ChaosReport(
        suite_id=suite.suite_id,
        suite_name=suite.name,
        created_at=ChaosReport.now_iso(),
        config={
            "runs": cfg.runs,
            "concurrency": cfg.concurrency,
            "seed": base_seed,
            "safe_logging": cfg.safe_logging,
            "otel_enabled": cfg.otel_enabled,
            "otel_metrics_enabled": cfg.otel_metrics_enabled,
            "otel_service_name": cfg.otel_service_name,
            "otel_endpoint": cfg.otel_endpoint,
        },
        score=score,
        metrics=metrics,
        per_task=per_task,
        top_failure_reasons=top_failure_reasons,
        task_runs=task_runs,
    )

    if baseline:
        if isinstance(baseline, ChaosReport):
            baseline_report = baseline
        else:
            baseline_report = ChaosReport.from_json(baseline)
        report.regression = _build_regression(report, baseline_report, cfg.regression_tolerance)

    telemetry.shutdown()
    return report
