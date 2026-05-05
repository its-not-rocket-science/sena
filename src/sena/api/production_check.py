from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sena.audit.chain import verify_audit_chain
from sena.api.config import ApiSettings
from sena.api.deployment_profiles import (
    VALID_DEPLOYMENT_PROFILES,
    validate_credible_pilot_profile,
)
from sena.integrations.jira import load_jira_mapping_config
from sena.integrations.servicenow import load_servicenow_mapping_config
from sena.integrations.webhook import load_webhook_mapping_config
from sena.policy.parser import PolicyParseError, load_policy_bundle
from sena.policy.release_signing import verify_release_manifest
from sena.policy.store import SQLitePolicyBundleRepository
from sena.storage_backends import get_capability

VALID_API_ROLES = {"admin", "policy_author", "reviewer", "deployer", "auditor"}
VALID_RUNTIME_MODES = {"development", "pilot", "production"}
VALID_POLICY_STORE_BACKENDS = {"filesystem", "sqlite"}
VALID_INGESTION_QUEUE_BACKENDS = {"memory", "redis", "sqlite"}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    fatal: bool
    details: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "fatal": self.fatal,
            "details": self.details,
        }


def _writable_dir(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    try:
        with tempfile.NamedTemporaryFile(
            prefix="sena-write-check-", dir=path, delete=True
        ):
            return True
    except OSError:
        return False


def _validate_env_coherence(settings: ApiSettings) -> list[str]:
    errors: list[str] = []
    if settings.runtime_mode not in VALID_RUNTIME_MODES:
        errors.append(
            f"SENA_RUNTIME_MODE must be one of {sorted(VALID_RUNTIME_MODES)}; got '{settings.runtime_mode}'"
        )
    if (
        settings.deployment_profile is not None
        and settings.deployment_profile not in VALID_DEPLOYMENT_PROFILES
    ):
        errors.append(
            "SENA_DEPLOYMENT_PROFILE must be one of "
            f"{sorted(VALID_DEPLOYMENT_PROFILES)}; got '{settings.deployment_profile}'"
        )
    if settings.policy_store_backend not in VALID_POLICY_STORE_BACKENDS:
        errors.append(
            "SENA_POLICY_STORE_BACKEND must be one of "
            f"{sorted(VALID_POLICY_STORE_BACKENDS)}; got '{settings.policy_store_backend}'"
        )
    if settings.policy_store_backend == "filesystem":
        policy_dir = Path(settings.policy_dir)
        if not policy_dir.exists() or not policy_dir.is_dir():
            errors.append(
                f"SENA_POLICY_DIR must point to an existing directory: {settings.policy_dir}"
            )
    if settings.policy_store_backend == "sqlite":
        if not settings.policy_store_sqlite_path:
            errors.append(
                "SENA_POLICY_STORE_SQLITE_PATH is required when SENA_POLICY_STORE_BACKEND=sqlite"
            )
        else:
            sqlite_parent = (
                Path(settings.policy_store_sqlite_path).expanduser().resolve().parent
            )
            if not sqlite_parent.exists() or not sqlite_parent.is_dir():
                errors.append(
                    "SENA_POLICY_STORE_SQLITE_PATH parent directory must exist: "
                    f"{settings.policy_store_sqlite_path}"
                )

    if settings.api_key and not settings.enable_api_key_auth:
        errors.append("SENA_API_KEY is set but SENA_API_KEY_ENABLED is not true")
    if settings.runtime_mode == "production" and not settings.enable_api_key_auth:
        errors.append("SENA_RUNTIME_MODE=production requires SENA_API_KEY_ENABLED=true")
    if settings.api_keys and settings.api_key:
        errors.append("Set only one of SENA_API_KEY or SENA_API_KEYS")
    if settings.enable_api_key_auth and not settings.api_key and not settings.api_keys:
        errors.append(
            "SENA_API_KEY_ENABLED=true requires SENA_API_KEY or SENA_API_KEYS to be set"
        )
    for _, role in settings.api_keys:
        if role not in VALID_API_ROLES:
            errors.append(
                f"SENA_API_KEYS contains unsupported role '{role}'. Expected one of: {sorted(VALID_API_ROLES)}"
            )
    if bool(settings.slack_bot_token) != bool(settings.slack_channel):
        errors.append(
            "SENA_SLACK_BOT_TOKEN and SENA_SLACK_CHANNEL must be set together when enabling Slack integration"
        )
    for config_path, env_name in (
        (settings.webhook_mapping_config_path, "SENA_WEBHOOK_MAPPING_CONFIG"),
        (settings.jira_mapping_config_path, "SENA_JIRA_MAPPING_CONFIG"),
        (settings.servicenow_mapping_config_path, "SENA_SERVICENOW_MAPPING_CONFIG"),
    ):
        if config_path:
            path = Path(config_path)
            if not path.exists() or not path.is_file():
                errors.append(
                    f"{env_name} must point to an existing file: {config_path}"
                )
    if settings.integration_reliability_sqlite_path:
        reliability_parent = (
            Path(settings.integration_reliability_sqlite_path)
            .expanduser()
            .resolve()
            .parent
        )
        if not reliability_parent.exists() or not reliability_parent.is_dir():
            errors.append(
                "SENA_INTEGRATION_RELIABILITY_SQLITE_PATH parent directory must exist: "
                f"{settings.integration_reliability_sqlite_path}"
            )
    if settings.ingestion_queue_backend not in VALID_INGESTION_QUEUE_BACKENDS:
        errors.append(
            "SENA_INGESTION_QUEUE_BACKEND must be one of "
            f"{sorted(VALID_INGESTION_QUEUE_BACKENDS)}"
        )
    if settings.ingestion_queue_backend == "redis" and not settings.ingestion_queue_redis_url:
        errors.append(
            "SENA_INGESTION_QUEUE_REDIS_URL is required when backend is redis"
        )
    if settings.runtime_mode in {"pilot", "production"} and settings.ingestion_queue_backend == "memory":
        errors.append(
            f"SENA_RUNTIME_MODE={settings.runtime_mode} forbids "
            "SENA_INGESTION_QUEUE_BACKEND=memory because queued inbound work "
            "must survive process restart. Configure redis or sqlite."
        )
    if settings.ingestion_queue_backend == "sqlite":
        sqlite_parent = Path(settings.processing_sqlite_path).expanduser().resolve().parent
        if not sqlite_parent.exists() or not sqlite_parent.is_dir():
            errors.append(
                "SENA_PROCESSING_SQLITE_PATH parent directory must exist when "
                "SENA_INGESTION_QUEUE_BACKEND=sqlite: "
                f"{settings.processing_sqlite_path}"
            )

    jira_enabled = bool(
        settings.jira_mapping_config_path
        or settings.jira_webhook_secret
        or settings.jira_webhook_secret_previous
        or settings.jira_write_back
    )
    servicenow_enabled = bool(
        settings.servicenow_mapping_config_path
        or settings.servicenow_webhook_secret
        or settings.servicenow_webhook_secret_previous
        or settings.servicenow_write_back
    )
    if settings.runtime_mode == "production":
        if not settings.audit_sink_jsonl:
            errors.append("SENA_RUNTIME_MODE=production requires SENA_AUDIT_SINK_JSONL")
        if not settings.bundle_signature_strict:
            errors.append(
                "SENA_RUNTIME_MODE=production requires SENA_BUNDLE_SIGNATURE_STRICT=true"
            )
        if not settings.bundle_signature_keyring_dir:
            errors.append(
                "SENA_RUNTIME_MODE=production requires SENA_BUNDLE_SIGNATURE_KEYRING_DIR"
            )
        elif not Path(settings.bundle_signature_keyring_dir).is_dir():
            errors.append(
                "SENA_BUNDLE_SIGNATURE_KEYRING_DIR must point to an existing directory: "
                f"{settings.bundle_signature_keyring_dir}"
            )
        if jira_enabled and not settings.jira_mapping_config_path:
            errors.append(
                "SENA_RUNTIME_MODE=production requires SENA_JIRA_MAPPING_CONFIG when Jira integration is enabled"
            )
        if servicenow_enabled and not settings.servicenow_mapping_config_path:
            errors.append(
                "SENA_RUNTIME_MODE=production requires SENA_SERVICENOW_MAPPING_CONFIG when ServiceNow integration is enabled"
            )
        if settings.integration_reliability_allow_inmemory:
            errors.append(
                "SENA_RUNTIME_MODE=production forbids SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true"
            )
        if (jira_enabled or servicenow_enabled) and not settings.integration_reliability_sqlite_path:
            errors.append(
                "SENA_RUNTIME_MODE=production requires SENA_INTEGRATION_RELIABILITY_SQLITE_PATH when Jira or ServiceNow integration is enabled"
            )
    if settings.runtime_mode in {"pilot", "production"}:
        if jira_enabled and not (
            settings.jira_webhook_secret or settings.jira_webhook_secret_previous
        ):
            errors.append(
                f"SENA_RUNTIME_MODE={settings.runtime_mode} requires "
                "SENA_JIRA_WEBHOOK_SECRET (or SENA_JIRA_WEBHOOK_SECRET_PREVIOUS) "
                "when Jira integration is enabled; allow-all verifier is disabled"
            )
        if servicenow_enabled and not (
            settings.servicenow_webhook_secret
            or settings.servicenow_webhook_secret_previous
        ):
            errors.append(
                f"SENA_RUNTIME_MODE={settings.runtime_mode} requires "
                "SENA_SERVICENOW_WEBHOOK_SECRET (or "
                "SENA_SERVICENOW_WEBHOOK_SECRET_PREVIOUS) when ServiceNow "
                "integration is enabled; allow-all verifier is disabled"
            )
    if settings.audit_verify_on_startup_strict and not settings.audit_sink_jsonl:
        errors.append(
            "SENA_AUDIT_VERIFY_ON_STARTUP_STRICT=true requires SENA_AUDIT_SINK_JSONL"
        )
    return errors


def _storage_backend_profile_warnings(settings: ApiSettings) -> list[str]:
    warnings: list[str] = []
    selected: list[tuple[str, str]] = [
        ("audit", settings.audit_storage_backend),
        ("policy_bundle", settings.policy_store_backend),
        ("runtime_processing", "sqlite"),
        ("ingestion_queue", settings.ingestion_queue_backend),
    ]
    reliability_backend = (
        "inmemory" if settings.integration_reliability_allow_inmemory else "sqlite"
    )
    selected.append(("integration_reliability", reliability_backend))
    for concern, backend in selected:
        capability = get_capability(concern, backend)
        if capability is None or settings.runtime_mode != "production":
            continue
        if capability.deployment_suitability == "local_dev":
            warnings.append(
                f"unsafe local/dev backend selected in production: {concern}={backend}"
            )
        elif capability.deployment_suitability == "pilot":
            warnings.append(
                f"pilot backend selected in production: {concern}={backend}"
            )
    return warnings


def _policy_backend_ready(settings: ApiSettings) -> list[str]:
    errors: list[str] = []
    if settings.policy_store_backend == "sqlite":
        if not settings.policy_store_sqlite_path:
            return [
                "SENA_POLICY_STORE_SQLITE_PATH is required when SENA_POLICY_STORE_BACKEND=sqlite"
            ]
        repo = SQLitePolicyBundleRepository(settings.policy_store_sqlite_path)
        repo.initialize()
        active = repo.get_active_bundle(settings.bundle_name)
        if active is None:
            errors.append(
                f"No active bundle found for '{settings.bundle_name}' in sqlite store"
            )
        elif not active.rules:
            errors.append(
                f"Active bundle '{settings.bundle_name}' in sqlite store has no rules"
            )
        return errors
    try:
        rules, metadata = load_policy_bundle(
            settings.policy_dir,
            bundle_name=settings.bundle_name,
            version=settings.bundle_version,
        )
    except PolicyParseError as exc:
        return [f"Failed to load policy bundle: {exc}"]
    if not rules:
        errors.append(
            f"Loaded bundle '{metadata.bundle_name}' version '{metadata.version}' contains no rules"
        )
    return errors


def _signature_ready(settings: ApiSettings) -> list[str]:
    manifest_path = (
        Path(settings.policy_dir) / settings.bundle_release_manifest_filename
    )
    if not manifest_path.exists():
        if settings.bundle_signature_strict:
            return [f"release manifest not found: {manifest_path}"]
        return []
    result = verify_release_manifest(
        Path(settings.policy_dir),
        manifest_path=manifest_path,
        keyring_dir=Path(settings.bundle_signature_keyring_dir)
        if settings.bundle_signature_keyring_dir
        else None,
        strict=settings.bundle_signature_strict,
    )
    return result.errors if not result.valid else []


def run_production_readiness_check(settings: ApiSettings) -> dict[str, Any]:
    checks: list[CheckResult] = []

    def add(name: str, *, fatal: bool, details: list[str]) -> None:
        checks.append(
            CheckResult(
                name=name,
                status="pass" if not details else "fail",
                fatal=fatal and bool(details),
                details=details,
            )
        )

    add(
        "environment variable coherence",
        fatal=True,
        details=_validate_env_coherence(settings),
    )

    auth_details: list[str] = []
    if settings.enable_api_key_auth and not (settings.api_key or settings.api_keys):
        auth_details.append(
            "API key auth is enabled but no API key material is configured"
        )
    if settings.runtime_mode == "production" and not settings.enable_api_key_auth:
        auth_details.append("Production mode must enable API key auth")
    add("auth configuration", fatal=True, details=auth_details)

    request_details: list[str] = []
    if settings.request_max_bytes <= 0:
        request_details.append("SENA_REQUEST_MAX_BYTES must be greater than 0")
    if settings.request_timeout_seconds <= 0:
        request_details.append("SENA_REQUEST_TIMEOUT_SECONDS must be greater than 0")
    if settings.request_timeout_seconds > 300:
        request_details.append(
            "SENA_REQUEST_TIMEOUT_SECONDS is above 300s; this is likely unsafe for production"
        )
    add("request limits and timeout sanity", fatal=True, details=request_details)

    add(
        "policy store backend readiness",
        fatal=True,
        details=_policy_backend_ready(settings),
    )
    add(
        "signature verification configuration",
        fatal=True,
        details=_signature_ready(settings),
    )

    integration_details: list[str] = []
    for label, config_path, loader in (
        ("webhook", settings.webhook_mapping_config_path, load_webhook_mapping_config),
        ("jira", settings.jira_mapping_config_path, load_jira_mapping_config),
        (
            "servicenow",
            settings.servicenow_mapping_config_path,
            load_servicenow_mapping_config,
        ),
    ):
        if not config_path:
            continue
        try:
            loader(config_path)
        except Exception as exc:
            integration_details.append(f"{label} mapping invalid: {exc}")
    add(
        "integration mapping existence and schema validity",
        fatal=True,
        details=integration_details,
    )
    add(
        "storage backend suitability",
        fatal=True,
        details=_storage_backend_profile_warnings(settings),
    )
    add(
        "credible pilot profile invariants",
        fatal=True,
        details=validate_credible_pilot_profile(settings),
    )

    audit_details: list[str] = []
    if settings.audit_sink_jsonl:
        sink_path = Path(settings.audit_sink_jsonl)
        parent = sink_path.expanduser().resolve().parent
        if not _writable_dir(parent):
            audit_details.append(
                f"audit sink parent directory is not writable: {parent}"
            )
        if settings.audit_verify_on_startup_strict and sink_path.exists():
            verification = verify_audit_chain(str(sink_path))
            if not verification.get("valid", False):
                detail = "; ".join(verification.get("errors", [])) or verification.get(
                    "error", "unknown error"
                )
                audit_details.append(f"audit verification failed: {detail}")
    elif settings.runtime_mode == "production":
        audit_details.append("audit sink is required in production mode")
    add("audit sink readiness", fatal=True, details=audit_details)

    writable_details: list[str] = []
    if settings.policy_store_backend == "sqlite" and settings.policy_store_sqlite_path:
        sqlite_parent = (
            Path(settings.policy_store_sqlite_path).expanduser().resolve().parent
        )
        if not _writable_dir(sqlite_parent):
            writable_details.append(
                f"sqlite parent directory is not writable: {sqlite_parent}"
            )
    if settings.bundle_signature_keyring_dir:
        keyring = Path(settings.bundle_signature_keyring_dir)
        if (
            not keyring.exists()
            or not keyring.is_dir()
            or not os.access(keyring, os.R_OK)
        ):
            writable_details.append(f"keyring dir is not readable: {keyring}")
    add("writable paths / restore prerequisites", fatal=True, details=writable_details)

    fatal_failures = [
        check.name for check in checks if check.status == "fail" and check.fatal
    ]
    return {
        "ok": not fatal_failures,
        "fatal_failure_count": len(fatal_failures),
        "fatal_failures": fatal_failures,
        "checks": [check.to_dict() for check in checks],
    }
