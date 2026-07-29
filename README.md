# ToolGauntlet

ToolGauntlet by HiLo Labs is a Python package and CLI for deterministic reliability testing of tool-using AI agents.

Public guide: [labs.hilomedia.com/products/toolgauntlet](https://labs.hilomedia.com/products/toolgauntlet).
Support: [labs.hilomedia.com/support](https://labs.hilomedia.com/support).

## Install

```bash
pip install toolgauntlet
toolgauntlet --version
```

The distribution, primary CLI, and public Python import are all `toolgauntlet`.
The prerelease `agent-chaos` commands and `agent_chaos` import remain available
as compatibility aliases.

## Quick start (CLI)

Generate a complete local baseline with no API key:

```bash
toolgauntlet quickstart --out-dir toolgauntlet-quickstart
```

This writes JSON, Markdown, and HTML baseline reports plus a copyable next-step
regression command. It uses the built-in deterministic adapter with safe logging
enabled and refuses to overwrite its files unless `--force` is supplied.

Build a custom workflow manually:

```bash
toolgauntlet list-suites
toolgauntlet init-suite --id my_suite_v1 --out-dir suites
toolgauntlet run --suite ecommerce_refunds_v1 --runs 10 --out report.json
toolgauntlet report --in report.json --format md --out report.md
toolgauntlet report --in report.json --format html --out report.html
```

Use a saved baseline as a release gate:

```bash
toolgauntlet run --suite ecommerce_refunds_v1 --runs 25 --out baseline.json
toolgauntlet run \
  --suite ecommerce_refunds_v1 \
  --runs 25 \
  --baseline baseline.json \
  --fail-on-regression \
  --regression-tolerance 1.0 \
  --out candidate.json
```

The [public guide](https://labs.hilomedia.com/products/toolgauntlet#quickstart)
includes the supported quickstart and release-gate workflow.

Signed pack workflow:

```bash
export TOOLGAUNTLET_PACK_KEY=your-shared-signing-key
toolgauntlet sign-pack --suite suites/my_suite_v1
toolgauntlet verify-pack --suite suites/my_suite_v1
toolgauntlet run --suite suites/my_suite_v1 --verify-pack --out report.json
```

OpenTelemetry traces (optional):

```bash
pip install "toolgauntlet[otel]"
# Requires an OTLP/HTTP collector reachable at the default endpoint,
# or pass --otel-endpoint with your collector URL.
toolgauntlet run --suite ecommerce_refunds_v1 --runs 5 --otel-enabled --otel-metrics-enabled
```

## Quick start (Python)

```python
from toolgauntlet import SuiteConfig, run_suite
from toolgauntlet.adapters import deterministic_demo_agent

report = run_suite(
    agent=deterministic_demo_agent,
    suite_path="ecommerce_refunds_v1",
    config=SuiteConfig(runs=10, concurrency=2),
)

report.save_json("report.json")
report.save_markdown("report.md")
```

## OpenAI-compatible adapter

```python
from toolgauntlet import SuiteConfig, run_suite
from toolgauntlet.adapters import OpenAICompatibleAdapterConfig, make_openai_tool_loop_adapter

agent = make_openai_tool_loop_adapter(
    OpenAICompatibleAdapterConfig(
        model="gpt-4o-mini",
        base_url="https://api.openai.com",
    )
)

report = run_suite(
    agent=agent,
    suite_path="ecommerce_refunds_v1",
    config=SuiteConfig(runs=5, concurrency=1),
)
```

## Additional adapter helpers
- `make_async_adapter`: use async agent callables with the synchronous harness interface.
- `make_langchain_like_adapter`: adapt invoke/ainvoke-style runnables.

See the included examples in [`examples/adapters/`](examples/adapters/).

## Budget-as-Code Proxy

Start and validate:

```bash
toolgauntlet-proxy validate-policy --policy examples/budget_proxy/policy.example.yaml
toolgauntlet-proxy serve \
  --host 127.0.0.1 \
  --port 8080 \
  --policy examples/budget_proxy/policy.example.yaml \
  --ledger logs/usage-ledger.sqlite
```

See the [public guide](https://labs.hilomedia.com/products/toolgauntlet#quickstart)
for deployment and operating guidance.

Key endpoints:
- `GET /healthz`
- `GET /metrics`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /admin/reload-policy`

Common environment variables:
- `OPENAI_API_KEY` or `BUDGET_UPSTREAM_API_KEY`
- `BUDGET_PROXY_API_KEY`
- `BUDGET_POLICY_PATH`
- `BUDGET_AUDIT_LOG_PATH`
- `BUDGET_LEDGER_PATH`
- `BUDGET_PROJECT_HEADER`
- `BUDGET_PROJECT_API_KEY_HEADER`
- `BUDGET_METRIC_NAMESPACE`
- `BUDGET_RATE_LIMIT_BACKEND` (`memory` or `redis`)
- `BUDGET_REDIS_URL` (required when backend is `redis`)
- `BUDGET_REDIS_KEY_PREFIX`
- `BUDGET_OTEL_ENABLED`
- `BUDGET_OTEL_METRICS_ENABLED`
- `BUDGET_OTEL_SERVICE_NAME`
- `BUDGET_OTEL_ENDPOINT`

To enable distributed rate limiting across proxy instances, install Redis support:

```bash
pip install "toolgauntlet[redis]"
```

## Included suites
- `ecommerce_refunds_v1`
- `support_triage_v1`
- `travel_booking_v1`

## Documentation and support

- [Public guide](https://labs.hilomedia.com/products/toolgauntlet)
- [Support](https://labs.hilomedia.com/support)
- [PyPI package](https://pypi.org/project/toolgauntlet/)
