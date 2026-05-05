from __future__ import annotations

from sena.api.config import ApiSettings

VALID_DEPLOYMENT_PROFILES = {"credible_pilot"}


def validate_credible_pilot_profile(settings: ApiSettings) -> list[str]:
    if settings.deployment_profile != "credible_pilot":
        return []
    errors: list[str] = []
    if settings.runtime_mode != "pilot":
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_RUNTIME_MODE=pilot"
        )
    if settings.enable_jwt_auth:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot forbids SENA_JWT_AUTH_ENABLED=true"
        )
    if not settings.enable_api_key_auth:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_API_KEY_ENABLED=true"
        )
    if not settings.api_keys:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_API_KEYS with explicit role bindings"
        )
    if settings.policy_store_backend != "sqlite":
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_POLICY_STORE_BACKEND=sqlite"
        )
    if settings.ingestion_queue_backend != "sqlite":
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_INGESTION_QUEUE_BACKEND=sqlite"
        )
    if settings.integration_reliability_allow_inmemory:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot forbids "
            "SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true"
        )
    if not settings.integration_reliability_sqlite_path:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires "
            "SENA_INTEGRATION_RELIABILITY_SQLITE_PATH"
        )
    if not settings.audit_sink_jsonl:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_AUDIT_SINK_JSONL"
        )
    if not settings.audit_verify_on_startup_strict:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires "
            "SENA_AUDIT_VERIFY_ON_STARTUP_STRICT=true"
        )
    if not settings.bundle_signature_strict:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_BUNDLE_SIGNATURE_STRICT=true"
        )
    if not settings.bundle_signature_keyring_dir:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_BUNDLE_SIGNATURE_KEYRING_DIR"
        )
    if settings.experimental_routes_enabled:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot forbids "
            "SENA_ENABLE_EXPERIMENTAL_ROUTES=true"
        )
    if settings.webhook_mapping_config_path:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot forbids SENA_WEBHOOK_MAPPING_CONFIG"
        )
    if settings.slack_bot_token or settings.slack_channel:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot forbids Slack integration"
        )
    if not settings.jira_mapping_config_path:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_JIRA_MAPPING_CONFIG"
        )
    if not settings.servicenow_mapping_config_path:
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_SERVICENOW_MAPPING_CONFIG"
        )
    if not (settings.jira_webhook_secret or settings.jira_webhook_secret_previous):
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires SENA_JIRA_WEBHOOK_SECRET "
            "(or SENA_JIRA_WEBHOOK_SECRET_PREVIOUS)"
        )
    if not (
        settings.servicenow_webhook_secret or settings.servicenow_webhook_secret_previous
    ):
        errors.append(
            "SENA_DEPLOYMENT_PROFILE=credible_pilot requires "
            "SENA_SERVICENOW_WEBHOOK_SECRET (or SENA_SERVICENOW_WEBHOOK_SECRET_PREVIOUS)"
        )
    return errors
