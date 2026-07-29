from __future__ import annotations

from toolgauntlet import SuiteConfig, run_suite
from toolgauntlet.adapters import (
    OpenAICompatibleAdapterConfig,
    make_openai_tool_loop_adapter,
)


if __name__ == "__main__":
    adapter = make_openai_tool_loop_adapter(
        OpenAICompatibleAdapterConfig(
            model="gpt-4o-mini",
            base_url="https://api.openai.com",
            max_turns=8,
            system_prompt="You are a policy-compliant operations agent.",
        )
    )

    report = run_suite(
        agent=adapter,
        suite_path="ecommerce_refunds_v1",
        config=SuiteConfig(runs=3, concurrency=1),
    )
    report.save_json("report-openai.json")
    report.save_markdown("report-openai.md")
