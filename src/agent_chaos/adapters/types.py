from __future__ import annotations

from typing import Any, Callable, Protocol


ToolExecutor = Callable[[str, dict[str, Any] | None], Any]


class AgentAdapter(Protocol):
    def __call__(
        self,
        prompt: str,
        tool_executor: ToolExecutor,
        context: dict[str, Any] | None = None,
    ) -> Any:
        ...
