from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ApiSettings:
    host: str = "0.0.0.0"
    port: int = 8000
    policy_dir: str = str(Path(__file__).resolve().parents[1] / "examples" / "policies")
    bundle_name: str = "default-bundle"
    bundle_version: str = "0.1.0-alpha"
    log_level: str = "INFO"
    enable_api_key_auth: bool = False
    api_key: str | None = None
    audit_sink_jsonl: str | None = None



def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in TRUE_VALUES



def _parse_int(raw: str | None, *, default: int) -> int:
    if raw is None:
        return default
    return int(raw)



def load_settings_from_env() -> ApiSettings:
    return ApiSettings(
        host=os.getenv("SENA_API_HOST", "0.0.0.0"),
        port=_parse_int(os.getenv("SENA_API_PORT"), default=8000),
        policy_dir=os.getenv(
            "SENA_POLICY_DIR",
            str(Path(__file__).resolve().parents[1] / "examples" / "policies"),
        ),
        bundle_name=os.getenv("SENA_BUNDLE_NAME", "default-bundle"),
        bundle_version=os.getenv("SENA_BUNDLE_VERSION", "0.1.0-alpha"),
        log_level=os.getenv("SENA_LOG_LEVEL", "INFO").upper(),
        enable_api_key_auth=_parse_bool(os.getenv("SENA_API_KEY_ENABLED"), default=False),
        api_key=os.getenv("SENA_API_KEY"),
        audit_sink_jsonl=os.getenv("SENA_AUDIT_SINK_JSONL"),
    )
