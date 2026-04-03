from __future__ import annotations

import os
from dataclasses import dataclass
import json

from sena.examples import DEFAULT_POLICY_DIR


TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ApiSettings:
    runtime_mode: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    policy_dir: str = str(DEFAULT_POLICY_DIR)
    bundle_name: str = "enterprise-compliance-controls"
    bundle_version: str = "2026.03"
    log_level: str = "INFO"
    enable_api_key_auth: bool = False
    api_key: str | None = None
    api_keys: tuple[tuple[str, str], ...] = ()
    audit_sink_jsonl: str | None = None
    audit_storage_backend: str = "local_file"
    audit_ship_destination: str | None = None
    policy_store_backend: str = "filesystem"
    policy_store_sqlite_path: str | None = None
    webhook_mapping_config_path: str | None = None
    jira_mapping_config_path: str | None = None
    jira_webhook_secret: str | None = None
    servicenow_mapping_config_path: str | None = None
    slack_bot_token: str | None = None
    slack_channel: str | None = None
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    request_max_bytes: int = 1_048_576
    request_timeout_seconds: float = 15.0
    bundle_release_manifest_filename: str = "release-manifest.json"
    bundle_signature_strict: bool = False
    bundle_signature_keyring_dir: str | None = None
    audit_verify_on_startup_strict: bool = False
    audit_verify_daily_enabled: bool = False
    promotion_gate_require_validation_artifact: bool = True
    promotion_gate_require_simulation: bool = True
    promotion_gate_required_scenario_ids: tuple[str, ...] = ()
    promotion_gate_max_changed_outcomes: int | None = None
    promotion_gate_max_regressions_by_outcome_type: tuple[tuple[str, int], ...] = ()
    promotion_gate_break_glass_enabled: bool = True


def _parse_api_keys(raw: str | None) -> tuple[tuple[str, str], ...]:
    if not raw:
        return ()
    pairs: list[tuple[str, str]] = []
    for item in raw.split(","):
        entry = item.strip()
        if not entry:
            continue
        key, sep, role = entry.partition(":")
        if not sep:
            raise ValueError("SENA_API_KEYS entries must use key:role format")
        normalized_key = key.strip()
        normalized_role = role.strip()
        if not normalized_key or not normalized_role:
            raise ValueError("SENA_API_KEYS entries must include both key and role")
        pairs.append((normalized_key, normalized_role))
    return tuple(pairs)


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in TRUE_VALUES


def _parse_int(raw: str | None, *, default: int) -> int:
    if raw is None:
        return default
    return int(raw)


def _parse_float(raw: str | None, *, default: float) -> float:
    if raw is None:
        return default
    return float(raw)


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _parse_regression_budgets(raw: str | None) -> tuple[tuple[str, int], ...]:
    if raw is None:
        return ()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(
            "SENA_PROMOTION_GATE_MAX_REGRESSIONS_BY_OUTCOME_TYPE must be a JSON object"
        )
    parsed: list[tuple[str, int]] = []
    for key, value in payload.items():
        parsed.append((str(key), int(value)))
    return tuple(parsed)


def load_settings_from_env() -> ApiSettings:
    return ApiSettings(
        runtime_mode=os.getenv("SENA_RUNTIME_MODE", "development").strip().lower(),
        host=os.getenv("SENA_API_HOST", "0.0.0.0"),
        port=_parse_int(os.getenv("SENA_API_PORT"), default=8000),
        policy_dir=os.getenv(
            "SENA_POLICY_DIR",
            str(DEFAULT_POLICY_DIR),
        ),
        bundle_name=os.getenv("SENA_BUNDLE_NAME", "enterprise-compliance-controls"),
        bundle_version=os.getenv("SENA_BUNDLE_VERSION", "2026.03"),
        log_level=os.getenv("SENA_LOG_LEVEL", "INFO").upper(),
        enable_api_key_auth=_parse_bool(
            os.getenv("SENA_API_KEY_ENABLED"), default=False
        ),
        api_key=os.getenv("SENA_API_KEY"),
        api_keys=_parse_api_keys(os.getenv("SENA_API_KEYS")),
        audit_sink_jsonl=os.getenv("SENA_AUDIT_SINK_JSONL"),
        audit_storage_backend=os.getenv("SENA_AUDIT_STORAGE_BACKEND", "local_file"),
        audit_ship_destination=os.getenv("SENA_AUDIT_SHIP_DESTINATION"),
        policy_store_backend=os.getenv("SENA_POLICY_STORE_BACKEND", "filesystem"),
        policy_store_sqlite_path=os.getenv("SENA_POLICY_STORE_SQLITE_PATH"),
        webhook_mapping_config_path=os.getenv("SENA_WEBHOOK_MAPPING_CONFIG"),
        jira_mapping_config_path=os.getenv("SENA_JIRA_MAPPING_CONFIG"),
        jira_webhook_secret=os.getenv("SENA_JIRA_WEBHOOK_SECRET"),
        servicenow_mapping_config_path=os.getenv("SENA_SERVICENOW_MAPPING_CONFIG"),
        slack_bot_token=os.getenv("SENA_SLACK_BOT_TOKEN"),
        slack_channel=os.getenv("SENA_SLACK_CHANNEL"),
        rate_limit_requests=_parse_int(
            os.getenv("SENA_RATE_LIMIT_REQUESTS"), default=120
        ),
        rate_limit_window_seconds=_parse_int(
            os.getenv("SENA_RATE_LIMIT_WINDOW_SECONDS"), default=60
        ),
        request_max_bytes=_parse_int(
            os.getenv("SENA_REQUEST_MAX_BYTES"), default=1_048_576
        ),
        request_timeout_seconds=_parse_float(
            os.getenv("SENA_REQUEST_TIMEOUT_SECONDS"), default=15.0
        ),
        bundle_release_manifest_filename=os.getenv(
            "SENA_BUNDLE_RELEASE_MANIFEST_FILENAME", "release-manifest.json"
        ),
        bundle_signature_strict=_parse_bool(
            os.getenv("SENA_BUNDLE_SIGNATURE_STRICT"), default=False
        ),
        bundle_signature_keyring_dir=os.getenv("SENA_BUNDLE_SIGNATURE_KEYRING_DIR"),
        audit_verify_on_startup_strict=_parse_bool(
            os.getenv("SENA_AUDIT_VERIFY_ON_STARTUP_STRICT"), default=False
        ),
        audit_verify_daily_enabled=_parse_bool(
            os.getenv("SENA_AUDIT_VERIFY_DAILY_ENABLED"), default=False
        ),
        promotion_gate_require_validation_artifact=_parse_bool(
            os.getenv("SENA_PROMOTION_GATE_REQUIRE_VALIDATION_ARTIFACT"), default=True
        ),
        promotion_gate_require_simulation=_parse_bool(
            os.getenv("SENA_PROMOTION_GATE_REQUIRE_SIMULATION"), default=True
        ),
        promotion_gate_required_scenario_ids=_parse_csv(
            os.getenv("SENA_PROMOTION_GATE_REQUIRED_SCENARIO_IDS")
        ),
        promotion_gate_max_changed_outcomes=(
            _parse_int(os.getenv("SENA_PROMOTION_GATE_MAX_CHANGED_OUTCOMES"), default=0)
            if os.getenv("SENA_PROMOTION_GATE_MAX_CHANGED_OUTCOMES") is not None
            else None
        ),
        promotion_gate_max_regressions_by_outcome_type=_parse_regression_budgets(
            os.getenv("SENA_PROMOTION_GATE_MAX_REGRESSIONS_BY_OUTCOME_TYPE")
        ),
        promotion_gate_break_glass_enabled=_parse_bool(
            os.getenv("SENA_PROMOTION_GATE_BREAK_GLASS_ENABLED"), default=True
        ),
    )
