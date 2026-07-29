from __future__ import annotations

import asyncio
import inspect
from threading import Thread
from typing import Any

from .types import AgentAdapter


def _run_awaitable(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
        in_running_loop = True
    except RuntimeError:
        in_running_loop = False

    if not in_running_loop:
        return asyncio.run(awaitable)

    result: dict[str, Any] = {}
    error: dict[str, Exception] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except Exception as exc:  # pragma: no cover - exercised via caller branches
            error["exc"] = exc

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "exc" in error:
        raise error["exc"]
    return result.get("value")


def make_async_adapter(async_agent: Any) -> AgentAdapter:
    """Wrap an async callable into ToolGauntlet's synchronous adapter interface."""

    if not callable(async_agent):
        raise ValueError("async_agent must be callable")

    def run(prompt: str, tool_executor: Any, context: dict[str, Any] | None = None) -> Any:
        value = async_agent(prompt, tool_executor, context)
        if inspect.isawaitable(value):
            return _run_awaitable(value)
        return value

    return run


def make_langchain_like_adapter(
    runnable: Any,
    *,
    input_key: str = "input",
    output_key: str = "output",
    include_tool_executor: bool = True,
    include_context: bool = True,
) -> AgentAdapter:
    """Adapt invoke/ainvoke-style runnables to the ToolGauntlet adapter contract.

    This helper is intentionally framework-agnostic and works with:
    - objects implementing `invoke(payload)` and/or `ainvoke(payload)`
    - plain callables that accept a single payload argument
    """

    has_invoke = callable(getattr(runnable, "invoke", None))
    has_ainvoke = callable(getattr(runnable, "ainvoke", None))
    if not has_invoke and not has_ainvoke and not callable(runnable):
        raise ValueError("runnable must be callable or implement invoke/ainvoke")

    if not input_key:
        raise ValueError("input_key must be non-empty")
    if not output_key:
        raise ValueError("output_key must be non-empty")

    def run(prompt: str, tool_executor: Any, context: dict[str, Any] | None = None) -> Any:
        payload: dict[str, Any] = {input_key: prompt}
        if include_tool_executor:
            payload["tool_executor"] = tool_executor
        if include_context:
            payload["context"] = context or {}

        if has_invoke:
            value = runnable.invoke(payload)
        elif has_ainvoke:
            value = runnable.ainvoke(payload)
        else:
            value = runnable(payload)

        if inspect.isawaitable(value):
            value = _run_awaitable(value)

        if isinstance(value, dict):
            if "output" in value:
                return value
            if output_key in value:
                normalized = {"output": value[output_key]}
                if "usage" in value and isinstance(value["usage"], dict):
                    normalized["usage"] = value["usage"]
                return normalized
        return value

    return run
