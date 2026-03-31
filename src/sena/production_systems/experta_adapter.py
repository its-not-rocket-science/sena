"""Deprecated legacy adapter shim.

The supported enterprise-compliance path does not use this module.
Use sena.engine.evaluator with structured policy rules instead.
"""

from __future__ import annotations

import warnings

__all__ = ["ExpertaAdapter"]


def __getattr__(name: str):
    if name == "ExpertaAdapter":
        warnings.warn(
            "sena.production_systems.experta_adapter is deprecated and kept for legacy compatibility.",
            DeprecationWarning,
            stacklevel=2,
        )
        from sena.legacy.production_systems.experta_adapter import ExpertaAdapter

        return ExpertaAdapter
    raise AttributeError(name)
