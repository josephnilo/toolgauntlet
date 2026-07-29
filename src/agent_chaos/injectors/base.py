from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from typing import Any, Protocol


@dataclass(slots=True)
class ToolCallContext:
    task_id: str
    run_index: int
    tool_name: str
    arguments: dict[str, Any]
    random: Random
    suite_state: dict[str, Any]
    events: list[str] = field(default_factory=list)


class Injector(Protocol):
    name: str
    probability: float

    def before_call(self, context: ToolCallContext) -> None: ...

    def after_call(self, context: ToolCallContext, output: Any) -> Any: ...


def should_trigger(probability: float, rnd: Random) -> bool:
    if probability <= 0.0:
        return False
    if probability >= 1.0:
        return True
    return rnd.random() < probability


class NoopInjector:
    name = "noop"

    def __init__(self, probability: float = 0.0, **_: Any) -> None:
        self.probability = probability

    def before_call(self, context: ToolCallContext) -> None:
        _ = context

    def after_call(self, context: ToolCallContext, output: Any) -> Any:
        _ = context
        return output


class InjectorPipeline:
    def __init__(self, injectors: list[Injector]) -> None:
        self.injectors = injectors

    def before_call(self, context: ToolCallContext) -> None:
        for injector in self.injectors:
            injector.before_call(context)

    def after_call(self, context: ToolCallContext, output: Any) -> Any:
        updated = output
        for injector in self.injectors:
            updated = injector.after_call(context, updated)
        return updated
