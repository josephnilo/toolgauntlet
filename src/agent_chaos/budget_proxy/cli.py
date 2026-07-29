from __future__ import annotations

import argparse
import sys

import uvicorn

from .app import create_app
from .config import load_config
from .policy import PolicyLoadError, load_policy


def cmd_validate_policy(args: argparse.Namespace) -> int:
    try:
        load_policy(args.policy)
    except PolicyLoadError as exc:
        print(f"invalid policy: {exc}", file=sys.stderr)
        return 1
    print("policy is valid")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    config = load_config(
        policy_path=args.policy,
        audit_log_path=args.audit_log,
        ledger_path=args.ledger,
        upstream_base_url=args.upstream_base_url,
        upstream_api_key=args.upstream_api_key,
        proxy_api_key=args.proxy_api_key,
        metric_namespace=args.metric_namespace,
        rate_limiter_backend=args.rate_limit_backend,
        redis_url=args.redis_url,
        redis_key_prefix=args.redis_key_prefix,
        otel_enabled=args.otel_enabled,
        otel_metrics_enabled=args.otel_metrics_enabled,
        otel_service_name=args.otel_service_name,
        otel_endpoint=args.otel_endpoint,
        timeout_seconds=args.timeout,
        host=args.host,
        port=args.port,
    )
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level=args.log_level)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toolgauntlet-proxy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Run Budget-as-Code FastAPI proxy")
    serve_parser.add_argument("--host", default=None, help="Host to bind (default env or 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=None, help="Port to bind (default env or 8080)")
    serve_parser.add_argument("--policy", default=None, help="Path to policy YAML")
    serve_parser.add_argument("--audit-log", default=None, help="Path to audit JSONL")
    serve_parser.add_argument("--ledger", default=None, help="Path to SQLite ledger (optional)")
    serve_parser.add_argument("--upstream-base-url", default=None, help="OpenAI-compatible upstream base URL")
    serve_parser.add_argument("--upstream-api-key", default=None, help="Upstream API key")
    serve_parser.add_argument("--proxy-api-key", default=None, help="Optional API key required by this proxy")
    serve_parser.add_argument(
        "--metric-namespace",
        default=None,
        help="Prometheus metric namespace prefix (default toolgauntlet_proxy)",
    )
    serve_parser.add_argument(
        "--rate-limit-backend",
        choices=["memory", "redis"],
        default=None,
        help="Rate limiter backend (default memory)",
    )
    serve_parser.add_argument(
        "--redis-url",
        default=None,
        help="Redis URL when using --rate-limit-backend redis",
    )
    serve_parser.add_argument(
        "--redis-key-prefix",
        default=None,
        help="Redis key prefix for rate limiter counters",
    )
    serve_parser.add_argument(
        "--otel-enabled",
        action="store_true",
        help="Enable OpenTelemetry trace export",
    )
    serve_parser.add_argument(
        "--otel-metrics-enabled",
        action="store_true",
        help="Enable OpenTelemetry metric export bridge",
    )
    serve_parser.add_argument(
        "--otel-service-name",
        default=None,
        help="OpenTelemetry service.name for proxy traces",
    )
    serve_parser.add_argument(
        "--otel-endpoint",
        default=None,
        help="OTLP/HTTP traces endpoint (optional)",
    )
    serve_parser.add_argument("--timeout", type=float, default=None, help="Upstream timeout seconds")
    serve_parser.add_argument("--log-level", default="info", help="Uvicorn log level")
    serve_parser.set_defaults(func=cmd_serve)

    validate_parser = subparsers.add_parser("validate-policy", help="Validate policy YAML")
    validate_parser.add_argument("--policy", required=True, help="Path to policy YAML")
    validate_parser.set_defaults(func=cmd_validate_policy)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
