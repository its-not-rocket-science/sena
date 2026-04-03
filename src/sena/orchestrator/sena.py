"""Compatibility stubs for removed legacy orchestrator."""

from __future__ import annotations


class SENA:  # pragma: no cover - compatibility stub
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise ImportError("sena.orchestrator.sena was removed with the legacy prototype stack.")


class TrainingHistory(SENA):
    pass
