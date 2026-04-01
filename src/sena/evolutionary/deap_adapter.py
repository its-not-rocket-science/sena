"""Deprecated legacy adapter shim.

The supported enterprise-compliance path does not use this module.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

__all__ = ["DEAPAdapter"]

if TYPE_CHECKING:
    from sena.legacy.evolutionary.deap_adapter import DEAPAdapter


def __getattr__(name: str):
    if name == "DEAPAdapter":
        warnings.warn(
            "sena.evolutionary.deap_adapter is deprecated and kept for legacy compatibility.",
            DeprecationWarning,
            stacklevel=2,
        )
        from sena.legacy.evolutionary.deap_adapter import DEAPAdapter

        return DEAPAdapter
    raise AttributeError(name)
