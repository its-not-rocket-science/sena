"""Deprecated legacy orchestrator shim.

The supported enterprise-compliance path is policy parsing + deterministic
rule evaluation from sena.engine.evaluator.
"""

from __future__ import annotations

import warnings

__all__ = ["SENA", "TrainingHistory"]


def __getattr__(name: str):
    if name in __all__:
        warnings.warn(
            "sena.orchestrator.sena is deprecated and kept for legacy compatibility.",
            DeprecationWarning,
            stacklevel=2,
        )
        from sena.legacy.orchestrator.sena import SENA, TrainingHistory

        return {"SENA": SENA, "TrainingHistory": TrainingHistory}[name]
    raise AttributeError(name)
