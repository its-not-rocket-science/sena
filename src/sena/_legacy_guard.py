"""Guardrails for legacy-module imports."""

from __future__ import annotations

import os
import warnings

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_true(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def enforce_legacy_import_policy(import_path: str) -> None:
    """Warn or fail when importing deprecated legacy modules.

    Behavior:
    - Always emits a deprecation warning for legacy imports.
    - Raises ImportError when strict legacy import mode is enabled.
    - Raises RuntimeError in production mode unless explicitly overridden.
    """

    strict_legacy_imports = _env_true("SENA_STRICT_LEGACY_IMPORTS")
    runtime_mode = os.getenv("SENA_RUNTIME_MODE", "development").strip().lower()
    allow_legacy_in_production = _env_true("SENA_ALLOW_LEGACY_IN_PRODUCTION")

    if runtime_mode == "production" and not allow_legacy_in_production:
        raise RuntimeError(
            "Legacy module import blocked in production runtime mode: "
            f"{import_path}. Set SENA_ALLOW_LEGACY_IN_PRODUCTION=true only for controlled migrations."
        )

    if strict_legacy_imports:
        raise ImportError(
            "Legacy module import blocked by strict mode "
            f"(SENA_STRICT_LEGACY_IMPORTS=true): {import_path}"
        )

    warnings.warn(
        "Importing legacy SENA modules is deprecated and outside the supported product path: "
        f"{import_path}. Use sena.policy.*, sena.engine.*, sena.api.*, and sena.cli.* instead.",
        DeprecationWarning,
        stacklevel=3,
    )
