import importlib
import sys

import pytest


def _drop_legacy_modules() -> None:
    for name in list(sys.modules):
        if name == "sena.legacy" or name.startswith("sena.legacy."):
            sys.modules.pop(name)


def test_legacy_import_warns_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENA_STRICT_LEGACY_IMPORTS", raising=False)
    monkeypatch.delenv("SENA_RUNTIME_MODE", raising=False)
    monkeypatch.delenv("SENA_ALLOW_LEGACY_IN_PRODUCTION", raising=False)
    _drop_legacy_modules()

    with pytest.deprecated_call(match="outside the supported product path"):
        importlib.import_module("sena.legacy")


def test_legacy_import_fails_in_strict_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENA_STRICT_LEGACY_IMPORTS", "true")
    monkeypatch.delenv("SENA_RUNTIME_MODE", raising=False)
    _drop_legacy_modules()

    with pytest.raises(ImportError, match="SENA_STRICT_LEGACY_IMPORTS"):
        importlib.import_module("sena.legacy")


def test_legacy_import_blocked_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SENA_STRICT_LEGACY_IMPORTS", raising=False)
    monkeypatch.setenv("SENA_RUNTIME_MODE", "production")
    monkeypatch.delenv("SENA_ALLOW_LEGACY_IN_PRODUCTION", raising=False)
    _drop_legacy_modules()

    with pytest.raises(RuntimeError, match="blocked in production runtime mode"):
        importlib.import_module("sena.legacy")


def test_legacy_import_can_be_overridden_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SENA_STRICT_LEGACY_IMPORTS", raising=False)
    monkeypatch.setenv("SENA_RUNTIME_MODE", "production")
    monkeypatch.setenv("SENA_ALLOW_LEGACY_IN_PRODUCTION", "true")
    _drop_legacy_modules()

    with pytest.deprecated_call(match="outside the supported product path"):
        importlib.import_module("sena.legacy")
