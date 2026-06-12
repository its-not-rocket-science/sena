from __future__ import annotations

import importlib


def test_supported_package_map_entrypoints_import() -> None:
    modules = [
        "sena.core_policy_engine",
        "sena.supported_integrations",
        "sena.runtime",
        "sena.audit_evidence",
        "sena.experimental",
    ]

    for module in modules:
        imported = importlib.import_module(module)
        assert imported is not None


def test_supported_integrations_exports_stable_symbols() -> None:
    mod = importlib.import_module("sena.supported_integrations")

    assert hasattr(mod, "JiraConnector")
    assert hasattr(mod, "ServiceNowConnector")
    assert hasattr(mod, "SQLiteIntegrationReliabilityStore")


def test_legacy_namespace_remains_absent() -> None:
    try:
        importlib.import_module("sena.legacy")
    except ModuleNotFoundError:
        return
    raise AssertionError("sena.legacy must remain absent")
