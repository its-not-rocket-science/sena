import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from sena.api.config import ApiSettings


def _settings(**kwargs) -> ApiSettings:
    defaults = {
        "policy_dir": "src/sena/examples/policies",
        "bundle_name": "enterprise-demo",
        "bundle_version": "2026.03",
        "enable_api_key_auth": False,
        "api_key": None,
        "api_keys": (),
        "audit_sink_jsonl": None,
        "rate_limit_requests": 120,
        "rate_limit_window_seconds": 60,
        "request_max_bytes": 1_048_576,
        "request_timeout_seconds": 15.0,
    }
    defaults.update(kwargs)
    return ApiSettings(**defaults)


def test_module_import_is_lightweight(monkeypatch) -> None:
    config_module = importlib.import_module("sena.api.config")
    calls: list[str] = []

    def _unexpected_env_load():
        calls.append("called")
        raise AssertionError("load_settings_from_env should not run during module import")

    monkeypatch.setattr(config_module, "load_settings_from_env", _unexpected_env_load)
    app_module = importlib.reload(importlib.import_module("sena.api.app"))

    assert calls == []
    assert app_module.app is not None


def test_app_factory_with_explicit_settings_skips_env_loading(monkeypatch) -> None:
    app_module = importlib.reload(importlib.import_module("sena.api.app"))

    def _unexpected_env_load():
        raise AssertionError("explicit settings should bypass environment loading")

    monkeypatch.setattr(app_module, "load_settings_from_env", _unexpected_env_load)

    app = app_module.create_app(_settings())
    client = TestClient(app)
    response = client.get("/v1/health")

    assert response.status_code == 200


def test_lazy_asgi_app_surfaces_startup_validation_errors() -> None:
    app_module = importlib.reload(importlib.import_module("sena.api.app"))
    lazy_app = app_module._LazyASGIApp(lambda: app_module.create_app(_settings(policy_dir="missing/path")))

    with pytest.raises(RuntimeError, match="SENA_POLICY_DIR must point to an existing directory"):
        with TestClient(lazy_app) as client:
            client.get("/v1/health")
