"""Compatibility stub for removed legacy production-system adapter."""

from __future__ import annotations


class ExpertaAdapter:  # pragma: no cover - compatibility stub
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise ImportError("sena.production_systems.experta_adapter is no longer available.")
