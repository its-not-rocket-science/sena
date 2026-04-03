import asyncio

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException

from sena.api.dependencies import verify_api_key


def test_verify_api_key_accepts_configured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENA_API_KEYS", "alpha,beta,gamma")

    assert asyncio.run(verify_api_key("beta")) == "beta"


def test_verify_api_key_rejects_unconfigured_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENA_API_KEYS", "alpha,beta")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(verify_api_key("delta"))

    assert exc_info.value.status_code == 403
