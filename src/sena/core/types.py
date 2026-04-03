"""Compatibility stubs for removed legacy research types."""

from __future__ import annotations


class Rule:  # pragma: no cover - compatibility stub
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise ImportError("sena.core.types legacy symbols were removed.")


class Trace(Rule):
    pass


class Genome(Rule):
    pass


class WorkingMemory(Rule):
    pass
