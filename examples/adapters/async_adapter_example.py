from __future__ import annotations

from toolgauntlet import SuiteConfig, run_suite
from toolgauntlet.adapters import make_async_adapter


async def async_agent(prompt: str, tool_executor, context: dict | None = None):
    lowered = prompt.lower()
    if "refund" in lowered:
        order = tool_executor("get_order", {"order_id": "123"})
        if isinstance(order, dict) and order.get("days_since_delivery", 999) <= 30:
            tool_executor("issue_refund", {"order_id": "123"})
            return {"output": "refund issued"}
        return {"output": "refund denied"}
    return {"output": "task completed"}


if __name__ == "__main__":
    adapter = make_async_adapter(async_agent)
    report = run_suite(
        agent=adapter,
        suite_path="ecommerce_refunds_v1",
        config=SuiteConfig(runs=2, concurrency=1, seed=42),
    )
    report.save_markdown("report.md")
    print(f"Score: {report.score.overall_score:.2f}")
