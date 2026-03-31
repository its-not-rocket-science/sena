"""Deprecated legacy types compatibility shim.

This module is retained only for backward compatibility with historical SENA
research-prototype imports. It is not part of the supported compliance-engine
path and may be removed in a future release.
"""

from __future__ import annotations

import warnings

__all__ = ["Rule", "Trace", "Genome", "WorkingMemory"]


def __getattr__(name: str):
    if name in __all__:
        warnings.warn(
            "sena.core.types is deprecated and part of the legacy research prototype. "
            "Use sena.core.models + sena.engine.evaluator for the supported compliance engine.",
            DeprecationWarning,
            stacklevel=2,
        )
        from sena.legacy.core import types as legacy_types

        return getattr(legacy_types, name)
    raise AttributeError(name)
