from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass(slots=True)
class Telemetry:
    enabled: bool
    traces_enabled: bool = False
    metrics_enabled: bool = False
    tracer: Any = None
    trace_provider: Any = None
    meter: Any = None
    metric_provider: Any = None
    _counter_instruments: dict[str, Any] = field(default_factory=dict)
    _histogram_instruments: dict[str, Any] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Any:
        if not self.traces_enabled or self.tracer is None:
            yield None
            return

        with self.tracer.start_as_current_span(name) as span:
            if attributes:
                for key, value in attributes.items():
                    if value is None:
                        continue
                    span.set_attribute(str(key), value)
            yield span

    def record_counter(
        self,
        name: str,
        value: int | float = 1,
        *,
        attributes: dict[str, Any] | None = None,
        unit: str | None = None,
        description: str | None = None,
    ) -> None:
        if not self.metrics_enabled or self.meter is None:
            return

        key = f"{name}|{unit or ''}|{description or ''}"
        instrument = self._counter_instruments.get(key)
        if instrument is None:
            with self._lock:
                instrument = self._counter_instruments.get(key)
                if instrument is None:
                    instrument = self.meter.create_counter(
                        name,
                        unit=unit or "",
                        description=description or "",
                    )
                    self._counter_instruments[key] = instrument

        instrument.add(value, attributes=attributes or {})

    def record_histogram(
        self,
        name: str,
        value: int | float,
        *,
        attributes: dict[str, Any] | None = None,
        unit: str | None = None,
        description: str | None = None,
    ) -> None:
        if not self.metrics_enabled or self.meter is None:
            return

        key = f"{name}|{unit or ''}|{description or ''}"
        instrument = self._histogram_instruments.get(key)
        if instrument is None:
            with self._lock:
                instrument = self._histogram_instruments.get(key)
                if instrument is None:
                    instrument = self.meter.create_histogram(
                        name,
                        unit=unit or "",
                        description=description or "",
                    )
                    self._histogram_instruments[key] = instrument

        instrument.record(value, attributes=attributes or {})

    def shutdown(self) -> None:
        for provider in (self.trace_provider, self.metric_provider):
            if provider is None:
                continue
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()


def _resolve_metric_endpoint(metric_endpoint: str | None, endpoint: str | None) -> str | None:
    if metric_endpoint:
        return metric_endpoint
    if endpoint and endpoint.rstrip("/").endswith("/v1/traces"):
        return endpoint.rstrip("/")[: -len("/v1/traces")] + "/v1/metrics"
    return endpoint


def build_telemetry(
    *,
    enabled: bool | None = None,
    traces_enabled: bool | None = None,
    metrics_enabled: bool = False,
    service_name: str,
    endpoint: str | None = None,
    metric_endpoint: str | None = None,
) -> Telemetry:
    traces_on = bool(traces_enabled) if traces_enabled is not None else bool(enabled)
    metrics_on = bool(metrics_enabled)
    if not traces_on and not metrics_on:
        return Telemetry(enabled=False)

    try:
        from opentelemetry.sdk.resources import Resource
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "OpenTelemetry mode requires optional dependencies. Install with: pip install toolgauntlet[otel]"
        ) from exc

    resource = Resource.create({"service.name": service_name})

    tracer = None
    trace_provider = None
    if traces_on:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError(
                "OpenTelemetry trace export requires optional dependencies. Install with: pip install toolgauntlet[otel]"
            ) from exc

        trace_provider = TracerProvider(resource=resource)
        trace_exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
        trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
        tracer = trace_provider.get_tracer(service_name)

    meter = None
    metric_provider = None
    if metrics_on:
        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError(
                "OpenTelemetry metric export requires optional dependencies. Install with: pip install toolgauntlet[otel]"
            ) from exc

        resolved_metric_endpoint = _resolve_metric_endpoint(metric_endpoint, endpoint)
        metric_exporter = (
            OTLPMetricExporter(endpoint=resolved_metric_endpoint)
            if resolved_metric_endpoint
            else OTLPMetricExporter()
        )
        metric_reader = PeriodicExportingMetricReader(metric_exporter)
        metric_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        meter = metric_provider.get_meter(service_name)

    return Telemetry(
        enabled=True,
        traces_enabled=traces_on,
        metrics_enabled=metrics_on,
        tracer=tracer,
        trace_provider=trace_provider,
        meter=meter,
        metric_provider=metric_provider,
    )
