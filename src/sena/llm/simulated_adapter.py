"""Deprecated legacy adapter shim.

The supported enterprise-compliance path does not require this module.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

__all__ = ["SimulatedLLMAdapter"]

if TYPE_CHECKING:
    from sena.legacy.llm.simulated_adapter import SimulatedLLMAdapter


def __getattr__(name: str):
    if name == "SimulatedLLMAdapter":
        warnings.warn(
            "sena.llm.simulated_adapter is deprecated and kept for legacy compatibility.",
            DeprecationWarning,
            stacklevel=2,
        )
        from sena.legacy.llm.simulated_adapter import SimulatedLLMAdapter

        return SimulatedLLMAdapter
    raise AttributeError(name)
