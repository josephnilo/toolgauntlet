from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SuccessSignal:
    type: str
    tool: str | None = None
    value: str | None = None


@dataclass(slots=True)
class TaskExpected:
    must_call_tools: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    success_signals: list[SuccessSignal] = field(default_factory=list)


@dataclass(slots=True)
class SuiteTask:
    id: str
    prompt: str
    expected: TaskExpected = field(default_factory=TaskExpected)


@dataclass(slots=True)
class SuiteTool:
    name: str
    schema_path: Path
    schema: dict[str, Any]


@dataclass(slots=True)
class InjectorSpec:
    type: str
    probability: float = 0.0
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChaosSpec:
    seed: int = 0
    injectors: list[InjectorSpec] = field(default_factory=list)


@dataclass(slots=True)
class SuiteDefinition:
    suite_id: str
    name: str
    description: str
    version: int
    root: Path
    tools: dict[str, SuiteTool]
    tasks: list[SuiteTask]
    chaos: ChaosSpec
    fixtures: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCallRecord:
    tool: str
    arguments: dict[str, Any]
    output: Any | None
    output_excerpt: str | None
    error: str | None
    latency_ms: float
    offset_ms: float
    timestamp: str
    attempt: int
    schema_compliant: bool | None
    injector_events: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RetrySummary:
    retries: int = 0
    bounded: bool = True
    backoff_present: bool = True
    storm_detected: bool = False


@dataclass(slots=True)
class TaskRunRecord:
    task_id: str
    run_index: int
    seed: int
    prompt_hash: str
    prompt_excerpt: str
    output_excerpt: str
    output_text: str
    tool_calls: list[ToolCallRecord]
    latency_ms: float
    success: bool
    tool_call_correct: bool
    failure_reasons: list[str] = field(default_factory=list)
    safety_violations: list[str] = field(default_factory=list)
    retry_summary: RetrySummary = field(default_factory=RetrySummary)
    exception: str | None = None
    usage: dict[str, Any] | None = None


@dataclass(slots=True)
class ScoreBreakdown:
    task_success_rate: float
    schema_compliance_rate: float
    retry_hygiene_rate: float
    latency_score: float
    safety_score: float
    overall_score: float


@dataclass(slots=True)
class RegressionComparison:
    baseline_score: float
    current_score: float
    delta: float
    regression: bool
    metric_deltas: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class ChaosReport:
    suite_id: str
    suite_name: str
    created_at: str
    config: dict[str, Any]
    score: ScoreBreakdown
    metrics: dict[str, Any]
    per_task: dict[str, dict[str, Any]]
    top_failure_reasons: list[dict[str, Any]]
    task_runs: list[TaskRunRecord]
    regression: RegressionComparison | None = None

    @classmethod
    def now_iso(cls) -> str:
        return datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.regression is None:
            payload["regression"] = None
        return payload

    def save_json(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2, ensure_ascii=True)
            handle.write("\n")

    @classmethod
    def from_json(cls, path: str | Path) -> "ChaosReport":
        source = Path(path)
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("Report JSON must be an object")
        return cls.from_dict(payload)

    def _regression_threshold(self) -> float:
        try:
            value = float(self.config.get("regression_tolerance", 0.0))
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, value)

    def _iter_metric_deltas(self) -> list[tuple[str, float]]:
        if not self.regression or not self.regression.metric_deltas:
            return []
        return sorted((name, float(delta)) for name, delta in self.regression.metric_deltas.items())

    @staticmethod
    def _format_metric_delta(name: str, delta: float) -> str:
        if name == "overall_score":
            return f"{delta:+.2f}"
        return f"{delta:+.4f}"

    def to_markdown(self) -> str:
        score = self.score
        lines = [
            f"# ToolGauntlet Report: {self.suite_name}",
            "",
            f"- Suite ID: `{self.suite_id}`",
            f"- Generated: `{self.created_at}`",
            f"- Overall Reliability Score: **{score.overall_score:.2f}/100**",
            "",
            "## Metric Breakdown",
            "",
            f"- Task success rate: {score.task_success_rate:.2%}",
            f"- Schema compliance rate: {score.schema_compliance_rate:.2%}",
            f"- Retry hygiene rate: {score.retry_hygiene_rate:.2%}",
            f"- Latency score: {score.latency_score:.2%}",
            f"- Safety score: {score.safety_score:.2%}",
            "",
            "## Top Failure Reasons",
            "",
        ]
        if self.top_failure_reasons:
            lines.extend([f"- {item['reason']}: {item['count']}" for item in self.top_failure_reasons])
        else:
            lines.append("- none")

        lines.extend(["", "## Per-task Breakdown", ""])
        for task_id, summary in sorted(self.per_task.items()):
            lines.append(f"### {task_id}")
            lines.append(f"- Runs: {summary.get('runs', 0)}")
            lines.append(f"- Success rate: {summary.get('success_rate', 0.0):.2%}")
            lines.append(f"- Avg latency: {summary.get('avg_latency_ms', 0.0):.1f} ms")
            lines.append(f"- Tool-call correctness: {summary.get('tool_call_correctness_rate', 0.0):.2%}")
            lines.append(f"- Safety violations: {summary.get('safety_violations', 0)}")
            lines.append("")

        if self.regression:
            threshold = self._regression_threshold()
            lines.extend(
                [
                    "## Regression Check",
                    "",
                    f"- Baseline score: {self.regression.baseline_score:.2f}",
                    f"- Current score: {self.regression.current_score:.2f}",
                    f"- Delta: {self.regression.delta:+.2f}",
                    f"- Regression: {'yes' if self.regression.regression else 'no'}",
                    f"- Significant metric delta threshold: ±{threshold:.4f}",
                    "",
                ]
            )
            metric_deltas = self._iter_metric_deltas()
            if metric_deltas:
                lines.extend(["### Metric Deltas", ""])
                for name, delta in metric_deltas:
                    significance = "significant" if abs(delta) >= threshold else "minor"
                    lines.append(f"- {name}: {self._format_metric_delta(name, delta)} ({significance})")
                lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def to_html(self) -> str:
        score = self.score
        threshold = self._regression_threshold()

        per_task_rows = "\n".join(
            (
                "<tr>"
                f"<td>{html.escape(task_id)}</td>"
                f"<td>{int(summary.get('runs', 0))}</td>"
                f"<td>{float(summary.get('success_rate', 0.0)):.2%}</td>"
                f"<td>{float(summary.get('avg_latency_ms', 0.0)):.1f}</td>"
                f"<td>{float(summary.get('tool_call_correctness_rate', 0.0)):.2%}</td>"
                f"<td>{int(summary.get('safety_violations', 0))}</td>"
                "</tr>"
            )
            for task_id, summary in sorted(self.per_task.items())
        )

        failures_html = "".join(
            f"<li>{html.escape(str(item.get('reason', 'unknown')))}: {int(item.get('count', 0))}</li>"
            for item in self.top_failure_reasons
        ) or "<li>none</li>"

        regression_html = ""
        if self.regression:
            metric_rows = "".join(
                (
                    "<tr>"
                    f"<td>{html.escape(name)}</td>"
                    f"<td>{self._format_metric_delta(name, delta)}</td>"
                    f"<td>{'significant' if abs(delta) >= threshold else 'minor'}</td>"
                    "</tr>"
                )
                for name, delta in self._iter_metric_deltas()
            )
            if not metric_rows:
                metric_rows = "<tr><td colspan='3'>none</td></tr>"

            regression_html = (
                "<section>"
                "<h2>Regression Check</h2>"
                "<ul>"
                f"<li>Baseline score: {self.regression.baseline_score:.2f}</li>"
                f"<li>Current score: {self.regression.current_score:.2f}</li>"
                f"<li>Delta: {self.regression.delta:+.2f}</li>"
                f"<li>Regression: {'yes' if self.regression.regression else 'no'}</li>"
                f"<li>Significant metric delta threshold: ±{threshold:.4f}</li>"
                "</ul>"
                "<h3>Metric Deltas</h3>"
                "<table>"
                "<thead><tr><th>Metric</th><th>Delta</th><th>Significance</th></tr></thead>"
                f"<tbody>{metric_rows}</tbody>"
                "</table>"
                "</section>"
            )

        return (
            "<!DOCTYPE html>"
            "<html lang='en'>"
            "<head>"
            "<meta charset='utf-8' />"
            f"<title>ToolGauntlet Report - {html.escape(self.suite_name)}</title>"
            "<style>"
            "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 24px; color: #111; }"
            "h1, h2, h3 { margin-bottom: 8px; }"
            "table { border-collapse: collapse; width: 100%; margin-bottom: 16px; }"
            "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }"
            "th { background: #f3f3f3; }"
            "code { background: #f5f5f5; padding: 1px 4px; }"
            "</style>"
            "</head>"
            "<body>"
            f"<h1>ToolGauntlet Report: {html.escape(self.suite_name)}</h1>"
            "<ul>"
            f"<li>Suite ID: <code>{html.escape(self.suite_id)}</code></li>"
            f"<li>Generated: <code>{html.escape(self.created_at)}</code></li>"
            f"<li>Overall Reliability Score: <strong>{score.overall_score:.2f}/100</strong></li>"
            "</ul>"
            "<section>"
            "<h2>Metric Breakdown</h2>"
            "<ul>"
            f"<li>Task success rate: {score.task_success_rate:.2%}</li>"
            f"<li>Schema compliance rate: {score.schema_compliance_rate:.2%}</li>"
            f"<li>Retry hygiene rate: {score.retry_hygiene_rate:.2%}</li>"
            f"<li>Latency score: {score.latency_score:.2%}</li>"
            f"<li>Safety score: {score.safety_score:.2%}</li>"
            "</ul>"
            "</section>"
            "<section>"
            "<h2>Top Failure Reasons</h2>"
            f"<ul>{failures_html}</ul>"
            "</section>"
            "<section>"
            "<h2>Per-task Breakdown</h2>"
            "<table>"
            "<thead>"
            "<tr>"
            "<th>Task</th><th>Runs</th><th>Success Rate</th><th>Avg Latency (ms)</th><th>Tool Correctness</th><th>Safety Violations</th>"
            "</tr>"
            "</thead>"
            f"<tbody>{per_task_rows}</tbody>"
            "</table>"
            "</section>"
            f"{regression_html}"
            "</body>"
            "</html>\n"
        )

    def save_markdown(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            handle.write(self.to_markdown())

    def save_html(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            handle.write(self.to_html())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChaosReport":
        score = ScoreBreakdown(**payload["score"])
        regression_payload = payload.get("regression")
        regression = RegressionComparison(**regression_payload) if regression_payload else None
        runs: list[TaskRunRecord] = []
        for run in payload.get("task_runs", []):
            tool_calls = []
            for call in run.get("tool_calls", []):
                if "offset_ms" not in call:
                    call = {**call, "offset_ms": 0.0}
                tool_calls.append(ToolCallRecord(**call))
            retry_summary = RetrySummary(**run.get("retry_summary", {}))
            runs.append(
                TaskRunRecord(
                    task_id=run["task_id"],
                    run_index=run["run_index"],
                    seed=run["seed"],
                    prompt_hash=run["prompt_hash"],
                    prompt_excerpt=run["prompt_excerpt"],
                    output_excerpt=run.get("output_excerpt", ""),
                    output_text=run.get("output_text", ""),
                    tool_calls=tool_calls,
                    latency_ms=run.get("latency_ms", 0.0),
                    success=run.get("success", False),
                    tool_call_correct=run.get("tool_call_correct", False),
                    failure_reasons=list(run.get("failure_reasons", [])),
                    safety_violations=list(run.get("safety_violations", [])),
                    retry_summary=retry_summary,
                    exception=run.get("exception"),
                    usage=run.get("usage"),
                )
            )
        return cls(
            suite_id=payload["suite_id"],
            suite_name=payload.get("suite_name", payload["suite_id"]),
            created_at=payload.get("created_at", cls.now_iso()),
            config=payload.get("config", {}),
            score=score,
            metrics=payload.get("metrics", {}),
            per_task=payload.get("per_task", {}),
            top_failure_reasons=payload.get("top_failure_reasons", []),
            task_runs=runs,
            regression=regression,
        )
