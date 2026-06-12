"""Experimental modules outside the supported product commitment.

Imports from this package are intentionally unstable and may change without
backwards-compatibility guarantees.
"""

from __future__ import annotations

import importlib
from types import ModuleType

_EXPERIMENTAL_MODULES = {
    "webhook": "sena.integrations.webhook",
    "slack": "sena.integrations.slack",
    "langchain": "sena.integrations.langchain",
    "llm": "sena.llm",
    "evolutionary": "sena.evolutionary",
    "production_systems": "sena.production_systems",
    "orchestrator": "sena.orchestrator",
    "monitoring": "sena.monitoring",
}

__all__ = sorted(_EXPERIMENTAL_MODULES)


def __getattr__(name: str) -> ModuleType:
    target = _EXPERIMENTAL_MODULES.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return importlib.import_module(target)
