from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any, Callable

from .base import Injector, InjectorPipeline
from .builtins import BUILTIN_INJECTORS

InjectorFactory = Callable[..., Injector]
INJECTOR_ENTRY_POINT_GROUPS = ("toolgauntlet.injectors", "agent_chaos.injectors")


class InjectorRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, InjectorFactory] = dict(BUILTIN_INJECTORS)
        self._load_entry_points()

    def _load_entry_points(self) -> None:
        for group in INJECTOR_ENTRY_POINT_GROUPS:
            try:
                points = entry_points(group=group)
            except TypeError:
                points = entry_points().get(group, [])

            for point in points:
                try:
                    factory = point.load()
                except Exception:
                    continue
                if callable(factory):
                    self._factories[point.name] = factory

    def create(self, injector_type: str, probability: float, config: dict[str, Any]) -> Injector:
        if injector_type not in self._factories:
            supported = ", ".join(sorted(self._factories.keys()))
            raise ValueError(f"Unknown injector '{injector_type}'. Supported: {supported}")
        return self._factories[injector_type](probability=probability, **config)


def build_pipeline(specs: list[dict[str, Any]]) -> InjectorPipeline:
    registry = InjectorRegistry()
    injectors = [
        registry.create(spec["type"], float(spec.get("probability", 0.0)), dict(spec.get("config", {})))
        for spec in specs
    ]
    return InjectorPipeline(injectors)


__all__ = ["Injector", "InjectorFactory", "InjectorPipeline", "InjectorRegistry", "build_pipeline"]
