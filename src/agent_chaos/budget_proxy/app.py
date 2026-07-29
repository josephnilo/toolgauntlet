from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from typing import Any, TypeVar

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

from .audit import AuditLogger
from .config import load_config
from .costing import response_cost_usd
from .enforcement import enforce_request, extract_model
from .ledger import UsageLedger
from .policy import PolicyLoadError, load_policy
from .rate_limit import RateLimiter, build_rate_limiter
from .redaction import redact_headers, redact_payload
from ..telemetry import build_telemetry
from .types import BudgetPolicy, ProxyConfig, UsageRecord
from .utils import coerce_json, request_id


_PROXY_EXCLUDE_HEADERS = {
    "host",
    "content-length",
    "connection",
}

T = TypeVar("T")


class ProxyMetrics:
    def __init__(self, namespace: str) -> None:
        normalized = namespace.strip().replace("-", "_")
        if not normalized:
            normalized = "toolgauntlet_proxy"
        self.namespace = normalized
        self.registry = CollectorRegistry(auto_describe=True)
        self.requests_total = Counter(
            f"{self.namespace}_requests_total",
            "Total number of proxy responses by endpoint/project/status.",
            ["endpoint", "project_id", "status_code"],
            registry=self.registry,
        )
        self.policy_decisions_total = Counter(
            f"{self.namespace}_policy_decisions_total",
            "Count of policy decision outcomes.",
            ["endpoint", "project_id", "code"],
            registry=self.registry,
        )
        self.latency_seconds = Histogram(
            f"{self.namespace}_request_latency_seconds",
            "Proxy request latency in seconds.",
            ["endpoint", "project_id"],
            registry=self.registry,
        )
        self.estimated_cost_usd_total = Counter(
            f"{self.namespace}_estimated_cost_usd_total",
            "Estimated request cost in USD (policy stage).",
            ["endpoint", "project_id"],
            registry=self.registry,
        )
        self.actual_cost_usd_total = Counter(
            f"{self.namespace}_actual_cost_usd_total",
            "Actual request cost in USD (from upstream usage when available).",
            ["endpoint", "project_id"],
            registry=self.registry,
        )

    def record(
        self,
        *,
        endpoint: str,
        project_id: str,
        status_code: int,
        latency_ms: float,
        decision_code: str,
        estimated_cost_usd: float = 0.0,
        actual_cost_usd: float | None = None,
    ) -> None:
        self.requests_total.labels(
            endpoint=endpoint,
            project_id=project_id,
            status_code=str(int(status_code)),
        ).inc()
        self.policy_decisions_total.labels(
            endpoint=endpoint,
            project_id=project_id,
            code=decision_code,
        ).inc()
        self.latency_seconds.labels(endpoint=endpoint, project_id=project_id).observe(max(0.0, latency_ms) / 1000.0)

        if estimated_cost_usd > 0:
            self.estimated_cost_usd_total.labels(endpoint=endpoint, project_id=project_id).inc(estimated_cost_usd)
        if actual_cost_usd is not None and actual_cost_usd > 0:
            self.actual_cost_usd_total.labels(endpoint=endpoint, project_id=project_id).inc(actual_cost_usd)


class ProxyState:
    def __init__(self, config: ProxyConfig) -> None:
        self.config = config
        self.policy: BudgetPolicy = load_policy(config.policy_path)
        self.audit = AuditLogger(config.audit_log_path)
        self.ledger = UsageLedger(config.ledger_path) if config.ledger_path else None
        self.rate_limiter: RateLimiter = build_rate_limiter(
            backend=config.rate_limiter_backend,
            redis_url=config.redis_url,
            redis_key_prefix=config.redis_key_prefix,
        )
        self.metrics = ProxyMetrics(namespace=config.metric_namespace)
        self.telemetry = build_telemetry(
            traces_enabled=config.otel_enabled,
            metrics_enabled=config.otel_metrics_enabled,
            service_name=config.otel_service_name,
            endpoint=config.otel_endpoint,
        )
        self.client = httpx.AsyncClient(base_url=config.upstream_base_url.rstrip("/"), timeout=config.timeout_seconds)

    def refresh_policy(self) -> None:
        self.policy = load_policy(self.config.policy_path)


def _allowed_project_spend(state: ProxyState, project_id: str) -> float:
    if state.ledger is None:
        return 0.0
    return state.ledger.current_month_spend(project_id)


def _sanitize_incoming_headers(headers: dict[str, str], upstream_api_key: str | None) -> dict[str, str]:
    proxied = {
        k: v
        for k, v in headers.items()
        if k.lower() not in _PROXY_EXCLUDE_HEADERS and k.lower() not in {"authorization", "proxy-authorization"}
    }
    if upstream_api_key:
        proxied["Authorization"] = f"Bearer {upstream_api_key}"
    return proxied


def _guard_proxy_api_key(request: Request, state: ProxyState) -> JSONResponse | None:
    expected = state.config.proxy_api_key
    if not expected:
        return None

    incoming = request.headers.get("authorization", "")
    token = incoming.removeprefix("Bearer ").strip() if incoming else ""
    if token != expected:
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "type": "invalid_request_error",
                    "message": "Unauthorized",
                }
            },
        )
    return None


def _extract_project_id(request: Request, state: ProxyState) -> str:
    project = request.headers.get(state.config.project_header)
    return project if project else "default"


def _resolve_project_value(mapping: dict[str, T], project_id: str) -> T | None:
    if project_id in mapping:
        return mapping[project_id]
    return mapping.get("default")


def _guard_project_access(request: Request, state: ProxyState, project_id: str) -> JSONResponse | None:
    project_key_map = state.policy.project_api_keys
    if not project_key_map:
        return None

    allowed_keys = _resolve_project_value(project_key_map, project_id)
    if not allowed_keys:
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "type": "invalid_request_error",
                    "message": f"Project '{project_id}' is not authorized",
                }
            },
        )

    provided_key = request.headers.get(state.config.project_api_key_header, "")
    if provided_key in allowed_keys:
        return None

    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "type": "invalid_request_error",
                "message": "Invalid project API key",
            }
        },
    )


def _requests_per_minute_limit(state: ProxyState, project_id: str) -> int | None:
    return _resolve_project_value(state.policy.requests_per_minute, project_id)


def _record_metrics(
    *,
    state: ProxyState,
    endpoint: str,
    project_id: str,
    status_code: int,
    latency_ms: float,
    decision_code: str,
    estimated_cost_usd: float = 0.0,
    actual_cost_usd: float | None = None,
) -> None:
    with state.telemetry.span(
        "toolgauntlet.proxy.decision",
        attributes={
            "toolgauntlet.endpoint": endpoint,
            "toolgauntlet.project_id": project_id,
            "toolgauntlet.status_code": int(status_code),
            "toolgauntlet.decision_code": decision_code,
            "toolgauntlet.latency_ms": float(latency_ms),
            "toolgauntlet.estimated_cost_usd": float(estimated_cost_usd),
        },
    ):
        state.metrics.record(
            endpoint=endpoint,
            project_id=project_id,
            status_code=status_code,
            latency_ms=latency_ms,
            decision_code=decision_code,
            estimated_cost_usd=estimated_cost_usd,
            actual_cost_usd=actual_cost_usd,
        )
        attrs = {
            "endpoint": endpoint,
            "project_id": project_id,
            "status_code": int(status_code),
            "decision_code": decision_code,
        }
        state.telemetry.record_counter(
            "toolgauntlet.proxy.requests_total",
            attributes=attrs,
            description="Proxy responses by endpoint/project/status.",
        )
        state.telemetry.record_counter(
            "toolgauntlet.proxy.policy_decisions_total",
            attributes={"endpoint": endpoint, "project_id": project_id, "decision_code": decision_code},
            description="Policy decision outcomes.",
        )
        state.telemetry.record_histogram(
            "toolgauntlet.proxy.request_latency_ms",
            latency_ms,
            unit="ms",
            attributes={"endpoint": endpoint, "project_id": project_id},
            description="Proxy request latency in milliseconds.",
        )
        if estimated_cost_usd > 0:
            state.telemetry.record_counter(
                "toolgauntlet.proxy.estimated_cost_usd_total",
                value=estimated_cost_usd,
                unit="USD",
                attributes={"endpoint": endpoint, "project_id": project_id},
                description="Estimated policy-stage request cost in USD.",
            )
        if actual_cost_usd is not None and actual_cost_usd > 0:
            state.telemetry.record_counter(
                "toolgauntlet.proxy.actual_cost_usd_total",
                value=actual_cost_usd,
                unit="USD",
                attributes={"endpoint": endpoint, "project_id": project_id},
                description="Actual upstream request cost in USD.",
            )


def _audit_event(
    *,
    rid: str,
    endpoint: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | None,
    response_status: int,
    project_id: str,
    model: str,
    latency_ms: float,
    policy_code: str,
    policy_message: str,
    estimated_cost_usd: float,
    error: str | None,
    request_headers: dict[str, str],
    state: ProxyState,
) -> dict[str, Any]:
    if state.policy.safe_logging:
        req_body = redact_payload(request_payload) if state.policy.redact_request_body else {"redacted": True}
        resp_body = redact_payload(response_payload) if (response_payload and state.policy.redact_response_body) else None
    else:
        req_body = request_payload
        resp_body = response_payload

    return {
        "request_id": rid,
        "endpoint": endpoint,
        "project_id": project_id,
        "model": model,
        "status_code": response_status,
        "latency_ms": latency_ms,
        "policy": {
            "code": policy_code,
            "message": policy_message,
            "estimated_cost_usd": estimated_cost_usd,
        },
        "error": error,
        "request_headers": redact_headers(request_headers),
        "request_body": req_body,
        "response_body": resp_body,
    }


def create_app(config: ProxyConfig | None = None) -> FastAPI:
    cfg = config or load_config()
    try:
        state = ProxyState(cfg)
    except (PolicyLoadError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"Cannot start proxy with current configuration: {exc}") from exc

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        yield
        await state.client.aclose()
        state.telemetry.shutdown()

    app = FastAPI(title="Budget-as-Code Proxy", version="0.1.2", lifespan=lifespan)
    app.state.proxy = state

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "upstream_base_url": state.config.upstream_base_url,
            "policy_path": state.config.policy_path,
            "ledger_enabled": bool(state.ledger),
        }

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=generate_latest(state.metrics.registry), media_type=CONTENT_TYPE_LATEST)

    @app.post("/admin/reload-policy")
    async def reload_policy(request: Request) -> JSONResponse:
        unauthorized = _guard_proxy_api_key(request, state)
        if unauthorized is not None:
            return unauthorized

        try:
            state.refresh_policy()
        except PolicyLoadError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})
        return JSONResponse(status_code=200, content={"ok": True})

    @app.get("/v1/models")
    async def models(request: Request) -> JSONResponse:
        started = time.perf_counter()
        endpoint = "/v1/models"
        project_id = _extract_project_id(request, state)

        unauthorized = _guard_proxy_api_key(request, state)
        if unauthorized is not None:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            _record_metrics(
                state=state,
                endpoint=endpoint,
                project_id=project_id,
                status_code=401,
                latency_ms=latency_ms,
                decision_code="proxy_auth_denied",
            )
            return unauthorized

        unauthorized_project = _guard_project_access(request, state, project_id)
        if unauthorized_project is not None:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            _record_metrics(
                state=state,
                endpoint=endpoint,
                project_id=project_id,
                status_code=401,
                latency_ms=latency_ms,
                decision_code="project_auth_denied",
            )
            return unauthorized_project

        if state.policy.allowed_models:
            data = [{"id": model, "object": "model", "owned_by": "policy"} for model in state.policy.allowed_models]
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            _record_metrics(
                state=state,
                endpoint=endpoint,
                project_id=project_id,
                status_code=200,
                latency_ms=latency_ms,
                decision_code="allowed",
            )
            return JSONResponse(status_code=200, content={"object": "list", "data": data})

        headers = _sanitize_incoming_headers(dict(request.headers), state.config.upstream_api_key)
        upstream = await state.client.get("/v1/models", headers=headers)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        _record_metrics(
            state=state,
            endpoint=endpoint,
            project_id=project_id,
            status_code=upstream.status_code,
            latency_ms=latency_ms,
            decision_code="allowed" if upstream.status_code < 400 else "upstream_error",
        )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    async def _proxy_openai_endpoint(endpoint: str, request: Request) -> Response:
        started = time.perf_counter()
        project_id = _extract_project_id(request, state)

        unauthorized = _guard_proxy_api_key(request, state)
        if unauthorized is not None:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            _record_metrics(
                state=state,
                endpoint=endpoint,
                project_id=project_id,
                status_code=401,
                latency_ms=latency_ms,
                decision_code="proxy_auth_denied",
            )
            return unauthorized

        rid = request_id()
        unauthorized_project = _guard_project_access(request, state, project_id)
        if unauthorized_project is not None:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            _record_metrics(
                state=state,
                endpoint=endpoint,
                project_id=project_id,
                status_code=401,
                latency_ms=latency_ms,
                decision_code="project_auth_denied",
            )
            return unauthorized_project

        try:
            payload = coerce_json(await request.json())
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            _record_metrics(
                state=state,
                endpoint=endpoint,
                project_id=project_id,
                status_code=400,
                latency_ms=latency_ms,
                decision_code="invalid_request",
            )
            return JSONResponse(status_code=400, content={"error": {"message": str(exc), "type": "invalid_request_error"}})

        model = extract_model(payload)
        limit = _requests_per_minute_limit(state, project_id)
        if limit is not None:
            allowed = state.rate_limiter.allow(f"{project_id}:{endpoint}", limit=limit, window_seconds=60.0)
            if not allowed:
                message = f"Rate limit exceeded for project '{project_id}' ({limit} req/min)"
                latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
                state.audit.write(
                    _audit_event(
                        rid=rid,
                        endpoint=endpoint,
                        request_payload=payload,
                        response_payload=None,
                        response_status=429,
                        project_id=project_id,
                        model=model,
                        latency_ms=latency_ms,
                        policy_code="rate_limited",
                        policy_message=message,
                        estimated_cost_usd=0.0,
                        error=message,
                        request_headers=dict(request.headers),
                        state=state,
                    )
                )
                _record_metrics(
                    state=state,
                    endpoint=endpoint,
                    project_id=project_id,
                    status_code=429,
                    latency_ms=latency_ms,
                    decision_code="rate_limited",
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "type": "rate_limit_error",
                            "code": "rate_limited",
                            "message": message,
                        }
                    },
                )

        current_spend = _allowed_project_spend(state, project_id)
        decision = enforce_request(
            payload=payload,
            endpoint=endpoint,
            project_id=project_id,
            policy=state.policy,
            current_month_spend_usd=current_spend,
        )

        if not decision.allowed:
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            state.audit.write(
                _audit_event(
                    rid=rid,
                    endpoint=endpoint,
                    request_payload=payload,
                    response_payload=None,
                    response_status=403,
                    project_id=project_id,
                    model=model,
                    latency_ms=latency_ms,
                    policy_code=decision.code,
                    policy_message=decision.message,
                    estimated_cost_usd=decision.estimated_cost_usd,
                    error=decision.message,
                    request_headers=dict(request.headers),
                    state=state,
                )
            )
            _record_metrics(
                state=state,
                endpoint=endpoint,
                project_id=project_id,
                status_code=403,
                latency_ms=latency_ms,
                decision_code=decision.code,
                estimated_cost_usd=decision.estimated_cost_usd,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "type": "policy_error",
                        "code": decision.code,
                        "message": decision.message,
                    }
                },
            )

        headers = _sanitize_incoming_headers(dict(request.headers), state.config.upstream_api_key)
        stream = bool(payload.get("stream", False))

        if stream:
            upstream_request = state.client.build_request("POST", endpoint, json=payload, headers=headers)
            upstream = await state.client.send(upstream_request, stream=True)

            async def _stream() -> Any:
                error_message: str | None = None
                response_chunks: list[str] = []
                try:
                    async for chunk in upstream.aiter_bytes():
                        if len(response_chunks) < 8:
                            try:
                                response_chunks.append(chunk.decode("utf-8", errors="ignore"))
                            except Exception:
                                pass
                        yield chunk
                except Exception as exc:
                    error_message = f"stream_error: {exc}"
                finally:
                    await upstream.aclose()
                    latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
                    response_excerpt = "".join(response_chunks)[:1000] if response_chunks else None
                    audit_response = {"stream_excerpt": response_excerpt} if response_excerpt else None
                    state.audit.write(
                        _audit_event(
                            rid=rid,
                            endpoint=endpoint,
                            request_payload=payload,
                            response_payload=audit_response,
                            response_status=upstream.status_code,
                            project_id=project_id,
                            model=model,
                            latency_ms=latency_ms,
                            policy_code=decision.code,
                            policy_message=decision.message,
                            estimated_cost_usd=decision.estimated_cost_usd,
                            error=error_message,
                            request_headers=dict(request.headers),
                            state=state,
                        )
                    )
                    if state.ledger is not None:
                        state.ledger.record(
                            UsageRecord(
                                request_id=rid,
                                project_id=project_id,
                                endpoint=endpoint,
                                model=model,
                                prompt_tokens=0,
                                completion_tokens=0,
                                cost_usd=decision.estimated_cost_usd,
                                status_code=upstream.status_code,
                                error=error_message,
                            )
                        )
                    _record_metrics(
                        state=state,
                        endpoint=endpoint,
                        project_id=project_id,
                        status_code=upstream.status_code,
                        latency_ms=latency_ms,
                        decision_code=decision.code if upstream.status_code < 400 else "upstream_error",
                        estimated_cost_usd=decision.estimated_cost_usd,
                        actual_cost_usd=decision.estimated_cost_usd,
                    )

            return StreamingResponse(
                _stream(),
                status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type", "text/event-stream"),
            )

        upstream = await state.client.post(endpoint, json=payload, headers=headers)
        response_payload: dict[str, Any] | None = None
        error_message: str | None = None

        try:
            response_payload = upstream.json()
        except json.JSONDecodeError:
            error_message = "upstream_response_not_json"

        if response_payload is not None:
            prompt_tokens, completion_tokens, actual_cost = response_cost_usd(
                model=model,
                payload=response_payload,
                policy=state.policy,
                fallback_estimated_cost_usd=decision.estimated_cost_usd,
            )
        else:
            prompt_tokens, completion_tokens, actual_cost = 0, 0, decision.estimated_cost_usd

        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)

        state.audit.write(
            _audit_event(
                rid=rid,
                endpoint=endpoint,
                request_payload=payload,
                response_payload=response_payload,
                response_status=upstream.status_code,
                project_id=project_id,
                model=model,
                latency_ms=latency_ms,
                policy_code=decision.code,
                policy_message=decision.message,
                estimated_cost_usd=actual_cost,
                error=error_message,
                request_headers=dict(request.headers),
                state=state,
            )
        )
        _record_metrics(
            state=state,
            endpoint=endpoint,
            project_id=project_id,
            status_code=upstream.status_code,
            latency_ms=latency_ms,
            decision_code=decision.code if upstream.status_code < 400 else "upstream_error",
            estimated_cost_usd=decision.estimated_cost_usd,
            actual_cost_usd=actual_cost,
        )

        if state.ledger is not None:
            state.ledger.record(
                UsageRecord(
                    request_id=rid,
                    project_id=project_id,
                    endpoint=endpoint,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost_usd=actual_cost,
                    status_code=upstream.status_code,
                    error=error_message,
                )
            )

        if response_payload is not None:
            return JSONResponse(status_code=upstream.status_code, content=response_payload)

        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> Response:
        return await _proxy_openai_endpoint("/v1/chat/completions", request)

    @app.post("/v1/responses")
    async def responses(request: Request) -> Response:
        return await _proxy_openai_endpoint("/v1/responses", request)

    return app
