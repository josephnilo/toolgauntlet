from __future__ import annotations

from toolgauntlet import SuiteConfig, run_suite
from toolgauntlet.adapters import make_langchain_like_adapter


class RunnableAgent:
    def invoke(self, payload: dict):
        prompt = payload["input"]
        tool_executor = payload["tool_executor"]

        if "refund" in prompt.lower():
            order = tool_executor("get_order", {"order_id": "123"})
            if isinstance(order, dict) and order.get("days_since_delivery", 999) <= 30:
                tool_executor("issue_refund", {"order_id": "123"})
                return {"result": "refund complete"}
            return {"result": "refund denied"}

        return {"result": "task completed"}


if __name__ == "__main__":
    adapter = make_langchain_like_adapter(RunnableAgent(), output_key="result")
    report = run_suite(
        agent=adapter,
        suite_path="ecommerce_refunds_v1",
        config=SuiteConfig(runs=2, concurrency=1, seed=42),
    )
    report.save_json("report.json")
    print(f"Score: {report.score.overall_score:.2f}")
