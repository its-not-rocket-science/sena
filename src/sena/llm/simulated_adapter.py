"""Compatibility stub for removed legacy LLM adapter."""

from __future__ import annotations


class SimulatedLLMAdapter:  # pragma: no cover - compatibility stub
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise ImportError("sena.llm.simulated_adapter is no longer available.")
