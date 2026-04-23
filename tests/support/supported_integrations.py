from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any


_FIXTURE_ROOT = Path("tests/fixtures/integrations")


def load_integration_fixture(connector: str, name: str) -> dict[str, Any]:
    fixture_path = _FIXTURE_ROOT / connector / f"{name}.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def hmac_sha256_hex(secret: str, payload_bytes: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
