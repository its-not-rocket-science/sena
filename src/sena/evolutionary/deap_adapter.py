"""Deprecated module retained only to provide deterministic failure messaging."""

from __future__ import annotations


class DEAPAdapter:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise ImportError(
            "sena.evolutionary.deap_adapter is no longer available. "
            "Legacy research adapters were removed from the supported SENA package."
        )
