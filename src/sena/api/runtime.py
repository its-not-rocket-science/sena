from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from sena.api.ingestion_queue import (
    build_ingestion_queue_backend,
    validate_ingestion_queue_settings,
)
from sena.api.config import ApiSettings
from sena.api.auth import VALID_APP_ROLES
from sena.api.metrics import ApiMetrics
from sena.core.enums import DecisionOutcome
from sena.core.models import PolicyBundleMetadata
from sena.policy.parser import PolicyParseError, load_policy_bundle
from sena.policy.release_signing import verify_release_manifest
from sena.policy.store import SQLitePolicyBundleRepository
from sena.api.processing_store import DeadLetterWorker, ProcessingStore
from sena.services.production_processing_service import ProductionProcessingService
from sena.services.automatic_recovery_service import AutomaticRecoveryService
from sena.services.exception_service import ExceptionService
from sena.services.async_jobs import InProcessJobManager
from sena.services.reliability_service import ReliabilityService
from sena.storage_backends import get_capability

logger = logging.getLogger(__name__)

VALID_API_ROLES = VALID_APP_ROLES
VALID_RUNTIME_MODES = {"development", "pilot", "production"}
VALID_POLICY_STORE_BACKENDS = {"filesystem", "sqlite"}
ROLE_ALLOWED_ENDPOINTS: dict[str, set[tuple[str, str]]] = {
    "policy_author": {
        ("POST", "/v1/bundle/register"),
        ("POST", "/v1/bundle/diff"),
        ("POST", "/v1/bundle/promotion/validate"),
        ("GET", "/v1/bundles/history"),
        ("GET", "/v1/bundles/active"),
        ("GET", "/v1/bundles/by-version"),
    },
    "reviewer": {
        ("GET", "/v1/operations/overview"),
        ("GET", "/v1/analytics/policy-efficacy"),
        ("POST", "/v1/bundle/promote"),
        ("POST", "/v1/admin/audit/config"),
        ("POST", "/v1/evaluate"),
        ("POST", "/v1/evaluate/review-package"),
        ("POST", "/v1/evaluate/batch"),
        ("GET", "/v1/decision/{decision_id}/explanation"),
        ("POST", "/v1/exceptions/create"),
        ("POST", "/v1/exceptions/approve"),
        ("GET", "/v1/exceptions/active"),
        ("POST", "/v1/integrations/webhook"),
        ("POST", "/v1/integrations/jira/webhook"),
        ("POST", "/v1/integrations/servicenow/webhook"),
        ("POST", "/v1/integrations/slack/interactions"),
        ("POST", "/v1/simulation"),
        ("POST", "/v1/simulation/replay"),
        ("POST", "/v1/jobs/simulation"),
        ("GET", "/v1/jobs/{job_id}"),
        ("GET", "/v1/jobs/{job_id}/result"),
        ("POST", "/v1/jobs/{job_id}/cancel"),
    },
    "deployer": {
        ("POST", "/v1/bundle/promote"),
        ("POST", "/v1/bundle/rollback"),
        ("GET", "/v1/bundles/history"),
        ("GET", "/v1/bundles/active"),
        ("GET", "/v1/bundles/by-version"),
    },
    "auditor": {
        ("GET", "/v1/operations/overview"),
        ("GET", "/v1/analytics/policy-efficacy"),
        ("GET", "/v1/audit/verify"),
        ("POST", "/v1/audit/hold/{decision_id}"),
        ("GET", "/v1/decision/{decision_id}/explanation"),
        ("GET", "/v1/decision/{decision_id}/attestations"),
        ("POST", "/v1/audit/verify/tree"),
        ("GET", "/v1/audit/hold"),
        ("GET", "/v1/admin/dlq"),
        ("GET", "/v1/admin/data-access"),
        ("GET", "/v1/admin/slo"),
        ("GET", "/v1/admin/data/payloads"),
        ("POST", "/v1/admin/data/payloads/{payload_id}/hold"),
        ("POST", "/v1/admin/audit/config"),
        ("GET", "/v1/integrations/{connector}/admin/outbound/completions"),
        ("GET", "/v1/integrations/{connector}/admin/outbound/dead-letter"),
        ("POST", "/v1/integrations/{connector}/admin/outbound/dead-letter/replay"),
        (
            "POST",
            "/v1/integrations/{connector}/admin/outbound/dead-letter/manual-redrive",
        ),
        ("GET", "/v1/integrations/{connector}/admin/outbound/duplicates/summary"),
        ("GET", "/v1/integrations/{connector}/admin/outbound/reliability/summary"),
        ("GET", "/v1/jobs/{job_id}"),
        ("GET", "/v1/jobs/{job_id}/result"),
    },
    "verifier": {
        ("GET", "/v1/decision/{decision_id}/attestations"),
        ("POST", "/v1/decision/{decision_id}/attestations/sign"),
    },
}

ROLE_ALLOWED_ENVIRONMENTS: dict[str, set[str]] = {
    "policy_author": {"development", "pilot"},
    "reviewer": {"development", "pilot", "production"},
    "deployer": {"pilot", "production"},
    "auditor": {"development", "pilot", "production"},
    "verifier": {"development", "pilot", "production"},
}

ROLE_ACTION_TYPE_DENYLIST: dict[str, set[str]] = {
    "policy_author": {"policy_promotion", "policy_deploy", "audit_config_change"},
    "reviewer": {"policy_deploy"},
    "deployer": {"policy_authoring"},
}


def _jira_integration_enabled(settings: ApiSettings) -> bool:
    return bool(
        settings.jira_mapping_config_path
        or settings.jira_webhook_secret
        or settings.jira_webhook_secret_previous
        or settings.jira_write_back
    )


def _servicenow_integration_enabled(settings: ApiSettings) -> bool:
    return bool(
        settings.servicenow_mapping_config_path
        or settings.servicenow_webhook_secret
        or settings.servicenow_webhook_secret_previous
        or settings.servicenow_write_back
    )


def _supported_reliability_integrations_enabled(settings: ApiSettings) -> bool:
    return _jira_integration_enabled(settings) or _servicenow_integration_enabled(
        settings
    )


def _resolve_connector_reliability_db_path(settings: ApiSettings) -> str | None:
    if settings.integration_reliability_sqlite_path:
        return settings.integration_reliability_sqlite_path
    if settings.integration_reliability_allow_inmemory:
        return None
    if _supported_reliability_integrations_enabled(settings):
        return settings.processing_sqlite_path
    return None


class EngineState:
    def __init__(
        self,
        settings: ApiSettings,
        rules: list,
        metadata: PolicyBundleMetadata,
        policy_repo: SQLitePolicyBundleRepository | None,
    ):
        self.settings = settings
        self.rules = rules
        self.metadata = metadata
        self.policy_repo = policy_repo
        self.metrics = ApiMetrics()
        self.metrics.observe_active_policies(count=len(rules))
        self.webhook_mapper: Any | None = None
        self.slack_client: Any | None = None
        self.connector_registry = _build_connector_registry()
        self.jira_connector: Any | None = None
        self.servicenow_connector: Any | None = None
        self.processing_store: ProcessingStore = ProcessingStore(
            settings.processing_sqlite_path
        )
        self.processing_service: ProductionProcessingService | None = None
        self.dlq_worker: DeadLetterWorker | None = None
        self.recovery_service: Any | None = None
        self.exception_service = ExceptionService()
        self.reliability_service: ReliabilityService | None = None
        self.job_manager = InProcessJobManager(
            max_workers=4,
            on_submitted=lambda job_type: self.metrics.observe_job_submitted(
                job_type=job_type
            ),
            on_terminal=lambda job_type, status: self.metrics.observe_job_terminal(
                job_type=job_type, status=status
            ),
        )


def _build_connector_registry(**kwargs: Any) -> Any:
    from sena.integrations.registry import build_connector_registry

    return build_connector_registry(**kwargs)


def verify_bundle_signature(
    *,
    policy_dir: str,
    manifest_filename: str,
    keyring_dir: str | None,
    strict: bool,
) -> tuple[bool, list[str], str]:
    manifest_path = Path(policy_dir) / manifest_filename
    if not manifest_path.exists():
        if strict:
            return (
                False,
                [f"release manifest not found: {manifest_path}"],
                str(manifest_path),
            )
        return True, [], str(manifest_path)
    result = verify_release_manifest(
        Path(policy_dir),
        manifest_path=manifest_path,
        keyring_dir=Path(keyring_dir) if keyring_dir else None,
        strict=strict,
    )
    return result.valid, result.errors, str(manifest_path)


def parse_default_decision(raw: str) -> DecisionOutcome:
    if raw == "ESCALATE":
        return DecisionOutcome.ESCALATE_FOR_HUMAN_REVIEW
    return DecisionOutcome(raw)


def load_runtime_bundle(
    runtime_settings: ApiSettings,
) -> tuple[list, PolicyBundleMetadata, SQLitePolicyBundleRepository | None]:
    if runtime_settings.policy_store_backend == "sqlite":
        if not runtime_settings.policy_store_sqlite_path:
            raise RuntimeError(
                "SENA_POLICY_STORE_SQLITE_PATH is required when SENA_POLICY_STORE_BACKEND=sqlite"
            )
        repo = SQLitePolicyBundleRepository(runtime_settings.policy_store_sqlite_path)
        repo.initialize()
        active = repo.get_active_bundle(runtime_settings.bundle_name)
        if active is None:
            raise RuntimeError(
                f"No active bundle found for '{runtime_settings.bundle_name}' in sqlite store"
            )
        if not active.rules:
            raise RuntimeError(
                f"Active bundle '{runtime_settings.bundle_name}' in sqlite store has no rules"
            )
        return active.rules, active.metadata, repo

    try:
        rules, metadata = load_policy_bundle(
            runtime_settings.policy_dir,
            bundle_name=runtime_settings.bundle_name,
            version=runtime_settings.bundle_version,
        )
    except PolicyParseError as exc:
        raise RuntimeError(f"Failed to load policy bundle: {exc}") from exc
    if not rules:
        raise RuntimeError(
            f"Loaded bundle '{metadata.bundle_name}' version '{metadata.version}' contains no rules"
        )
    return rules, metadata, None


def validate_startup_settings(runtime_settings: ApiSettings) -> None:
    _validate_runtime_mode_and_policy_store(runtime_settings)
    _validate_data_regions(runtime_settings)
    _validate_api_auth_settings(runtime_settings)
    _validate_connector_config_paths(runtime_settings)
    _validate_reliability_sqlite_path(runtime_settings)
    _validate_production_startup_requirements(runtime_settings)
    _validate_supported_connector_webhook_verification_policy(runtime_settings)
    _validate_operational_limits(runtime_settings)
    _warn_or_fail_for_storage_profiles(runtime_settings)


def _warn_or_fail_for_storage_profiles(runtime_settings: ApiSettings) -> None:
    selected: list[tuple[str, str]] = [
        ("audit", runtime_settings.audit_storage_backend),
        ("policy_bundle", runtime_settings.policy_store_backend),
        ("runtime_processing", "sqlite"),
        ("ingestion_queue", runtime_settings.ingestion_queue_backend),
    ]
    reliability_backend = (
        "inmemory"
        if runtime_settings.integration_reliability_allow_inmemory
        else "sqlite"
    )
    selected.append(("integration_reliability", reliability_backend))

    for concern, backend in selected:
        capability = get_capability(concern, backend)
        if capability is None:
            continue
        if runtime_settings.runtime_mode == "production":
            if capability.deployment_suitability == "local_dev":
                raise RuntimeError(
                    "SENA_RUNTIME_MODE=production forbids local/dev storage backend "
                    f"'{backend}' for concern '{concern}'. {capability.notes}"
                )
            if capability.deployment_suitability == "pilot":
                logger.warning(
                    "Production startup using pilot storage backend '%s' for '%s'. "
                    "Concurrency model: %s. Durability assumptions: %s. Notes: %s",
                    backend,
                    concern,
                    capability.concurrency_model,
                    capability.durability_assumptions,
                    capability.notes,
                )


def _validate_runtime_mode_and_policy_store(runtime_settings: ApiSettings) -> None:
    if runtime_settings.runtime_mode not in VALID_RUNTIME_MODES:
        raise RuntimeError(
            f"SENA_RUNTIME_MODE must be one of {sorted(VALID_RUNTIME_MODES)}; got '{runtime_settings.runtime_mode}'"
        )
    if runtime_settings.policy_store_backend not in VALID_POLICY_STORE_BACKENDS:
        raise RuntimeError(
            "SENA_POLICY_STORE_BACKEND must be one of "
            f"{sorted(VALID_POLICY_STORE_BACKENDS)}; got '{runtime_settings.policy_store_backend}'"
        )
    if runtime_settings.policy_store_backend == "filesystem":
        policy_dir = Path(runtime_settings.policy_dir)
        if not policy_dir.exists() or not policy_dir.is_dir():
            raise RuntimeError(
                f"SENA_POLICY_DIR must point to an existing directory: {runtime_settings.policy_dir}"
            )
    if runtime_settings.policy_store_backend == "sqlite":
        if not runtime_settings.policy_store_sqlite_path:
            raise RuntimeError(
                "SENA_POLICY_STORE_SQLITE_PATH is required when SENA_POLICY_STORE_BACKEND=sqlite"
            )
        sqlite_parent = (
            Path(runtime_settings.policy_store_sqlite_path)
            .expanduser()
            .resolve()
            .parent
        )
        if not sqlite_parent.exists() or not sqlite_parent.is_dir():
            raise RuntimeError(
                "SENA_POLICY_STORE_SQLITE_PATH parent directory must exist: "
                f"{runtime_settings.policy_store_sqlite_path}"
            )


def _validate_data_regions(runtime_settings: ApiSettings) -> None:
    if not runtime_settings.data_allowed_regions:
        raise RuntimeError("SENA_DATA_ALLOWED_REGIONS must include at least one region")
    if runtime_settings.data_default_region not in set(
        runtime_settings.data_allowed_regions
    ):
        raise RuntimeError(
            "SENA_DATA_DEFAULT_REGION must be present in SENA_DATA_ALLOWED_REGIONS"
        )


def _validate_api_auth_settings(runtime_settings: ApiSettings) -> None:
    if runtime_settings.api_key and not runtime_settings.enable_api_key_auth:
        raise RuntimeError("SENA_API_KEY is set but SENA_API_KEY_ENABLED is not true")
    if (
        runtime_settings.runtime_mode == "production"
        and not runtime_settings.enable_api_key_auth
        and not runtime_settings.enable_jwt_auth
    ):
        raise RuntimeError(
            "SENA_RUNTIME_MODE=production requires SENA_API_KEY_ENABLED=true or SENA_JWT_AUTH_ENABLED=true"
        )
    if runtime_settings.api_keys and runtime_settings.api_key:
        raise RuntimeError("Set only one of SENA_API_KEY or SENA_API_KEYS")
    if (
        runtime_settings.enable_api_key_auth
        and not runtime_settings.api_key
        and not runtime_settings.api_keys
    ):
        raise RuntimeError(
            "SENA_API_KEY_ENABLED=true requires SENA_API_KEY or SENA_API_KEYS to be set"
        )
    for _, role in runtime_settings.api_keys:
        if role not in VALID_API_ROLES:
            raise RuntimeError(
                f"SENA_API_KEYS contains unsupported role '{role}'. Expected one of: {sorted(VALID_API_ROLES)}"
            )
    for _, role in runtime_settings.jwt_role_mapping:
        if role not in VALID_API_ROLES:
            raise RuntimeError(
                f"SENA_JWT_ROLE_MAPPING contains unsupported target role '{role}'. Expected one of: {sorted(VALID_API_ROLES)}"
            )
    if runtime_settings.enable_jwt_auth and not runtime_settings.jwt_hs256_secret:
        raise RuntimeError(
            "SENA_JWT_AUTH_ENABLED=true requires SENA_JWT_HS256_SECRET for local/dev verification"
        )
    if runtime_settings.enable_jwt_auth and not runtime_settings.jwt_role_claim.strip():
        raise RuntimeError("SENA_JWT_ROLE_CLAIM must not be empty when JWT auth is enabled")
    if runtime_settings.step_up_max_age_seconds <= 0:
        raise RuntimeError("SENA_STEP_UP_MAX_AGE_SECONDS must be greater than 0")
    if runtime_settings.require_signed_step_up and not runtime_settings.step_up_hs256_secret:
        raise RuntimeError(
            "SENA_REQUIRE_SIGNED_STEP_UP=true requires SENA_STEP_UP_HS256_SECRET"
        )
    if bool(runtime_settings.slack_bot_token) != bool(runtime_settings.slack_channel):
        raise RuntimeError(
            "SENA_SLACK_BOT_TOKEN and SENA_SLACK_CHANNEL must be set together when enabling Slack integration"
        )


def _validate_connector_config_paths(runtime_settings: ApiSettings) -> None:
    for config_path, env_name in (
        (runtime_settings.webhook_mapping_config_path, "SENA_WEBHOOK_MAPPING_CONFIG"),
        (runtime_settings.jira_mapping_config_path, "SENA_JIRA_MAPPING_CONFIG"),
        (
            runtime_settings.servicenow_mapping_config_path,
            "SENA_SERVICENOW_MAPPING_CONFIG",
        ),
    ):
        if config_path:
            path = Path(config_path)
            if not path.exists() or not path.is_file():
                raise RuntimeError(
                    f"{env_name} must point to an existing file: {config_path}"
                )


def _validate_reliability_sqlite_path(runtime_settings: ApiSettings) -> None:
    if runtime_settings.integration_reliability_sqlite_path:
        reliability_parent = (
            Path(runtime_settings.integration_reliability_sqlite_path)
            .expanduser()
            .resolve()
            .parent
        )
        if not reliability_parent.exists() or not reliability_parent.is_dir():
            raise RuntimeError(
                "SENA_INTEGRATION_RELIABILITY_SQLITE_PATH parent directory must exist: "
                f"{runtime_settings.integration_reliability_sqlite_path}"
            )


def _validate_production_startup_requirements(runtime_settings: ApiSettings) -> None:
    if runtime_settings.runtime_mode == "production":
        if not runtime_settings.audit_sink_jsonl:
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production requires SENA_AUDIT_SINK_JSONL"
            )
        if not runtime_settings.bundle_signature_strict:
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production requires SENA_BUNDLE_SIGNATURE_STRICT=true"
            )
        if not runtime_settings.bundle_signature_keyring_dir:
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production requires SENA_BUNDLE_SIGNATURE_KEYRING_DIR"
            )
        keyring_dir = Path(runtime_settings.bundle_signature_keyring_dir)
        if not keyring_dir.exists() or not keyring_dir.is_dir():
            raise RuntimeError(
                "SENA_BUNDLE_SIGNATURE_KEYRING_DIR must point to an existing directory: "
                f"{runtime_settings.bundle_signature_keyring_dir}"
            )
        if runtime_settings.integration_reliability_allow_inmemory:
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production forbids "
                "SENA_INTEGRATION_RELIABILITY_ALLOW_INMEMORY=true"
            )
        if _supported_reliability_integrations_enabled(runtime_settings) and not (
            runtime_settings.integration_reliability_sqlite_path
        ):
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production requires "
                "SENA_INTEGRATION_RELIABILITY_SQLITE_PATH when Jira or ServiceNow integration is enabled"
            )
        if _jira_integration_enabled(runtime_settings) and not (
            runtime_settings.jira_mapping_config_path
        ):
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production requires SENA_JIRA_MAPPING_CONFIG when Jira integration is enabled"
            )
        if _servicenow_integration_enabled(runtime_settings) and not (
            runtime_settings.servicenow_mapping_config_path
        ):
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production requires SENA_SERVICENOW_MAPPING_CONFIG when ServiceNow integration is enabled"
            )
        if _jira_integration_enabled(runtime_settings) and not (
            runtime_settings.jira_webhook_secret
            or runtime_settings.jira_webhook_secret_previous
        ):
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production requires SENA_JIRA_WEBHOOK_SECRET (or SENA_JIRA_WEBHOOK_SECRET_PREVIOUS) when Jira integration is enabled"
            )
        if _servicenow_integration_enabled(runtime_settings) and not (
            runtime_settings.servicenow_webhook_secret
            or runtime_settings.servicenow_webhook_secret_previous
        ):
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production requires SENA_SERVICENOW_WEBHOOK_SECRET (or SENA_SERVICENOW_WEBHOOK_SECRET_PREVIOUS) when ServiceNow integration is enabled"
            )
        if runtime_settings.jira_mapping_config_path:
            from sena.integrations.jira import (
                JiraIntegrationError,
                load_jira_mapping_config,
            )

            try:
                load_jira_mapping_config(runtime_settings.jira_mapping_config_path)
            except JiraIntegrationError as exc:
                raise RuntimeError(
                    f"SENA_JIRA_MAPPING_CONFIG is invalid for production startup: {exc}"
                ) from exc
        if runtime_settings.servicenow_mapping_config_path:
            from sena.integrations.servicenow import (
                ServiceNowIntegrationError,
                load_servicenow_mapping_config,
            )

            try:
                load_servicenow_mapping_config(
                    runtime_settings.servicenow_mapping_config_path
                )
            except ServiceNowIntegrationError as exc:
                raise RuntimeError(
                    "SENA_SERVICENOW_MAPPING_CONFIG is invalid for production startup: "
                    f"{exc}"
                ) from exc


def _validate_supported_connector_webhook_verification_policy(
    runtime_settings: ApiSettings,
) -> None:
    jira_enabled = _jira_integration_enabled(runtime_settings)
    jira_has_secret = bool(
        runtime_settings.jira_webhook_secret
        or runtime_settings.jira_webhook_secret_previous
    )
    servicenow_enabled = _servicenow_integration_enabled(runtime_settings)
    servicenow_has_secret = bool(
        runtime_settings.servicenow_webhook_secret
        or runtime_settings.servicenow_webhook_secret_previous
    )
    if runtime_settings.runtime_mode in {"pilot", "production"}:
        if jira_enabled and not jira_has_secret:
            raise RuntimeError(
                f"SENA_RUNTIME_MODE={runtime_settings.runtime_mode} requires "
                "SENA_JIRA_WEBHOOK_SECRET (or SENA_JIRA_WEBHOOK_SECRET_PREVIOUS) "
                "when Jira integration is enabled; allow-all verifier is disabled."
            )
        if servicenow_enabled and not servicenow_has_secret:
            raise RuntimeError(
                f"SENA_RUNTIME_MODE={runtime_settings.runtime_mode} requires "
                "SENA_SERVICENOW_WEBHOOK_SECRET "
                "(or SENA_SERVICENOW_WEBHOOK_SECRET_PREVIOUS) when ServiceNow "
                "integration is enabled; allow-all verifier is disabled."
            )
        return

    if jira_enabled and not jira_has_secret:
        logger.warning(
            "SENA_RUNTIME_MODE=development starting Jira integration with "
            "AllowAllJiraWebhookVerifier because webhook secret is missing. "
            "Inbound Jira events are forgeable in this mode."
        )
    if servicenow_enabled and not servicenow_has_secret:
        logger.warning(
            "SENA_RUNTIME_MODE=development starting ServiceNow integration with "
            "AllowAllServiceNowWebhookVerifier because webhook secret is missing. "
            "Inbound ServiceNow events are forgeable in this mode."
        )


def _validate_operational_limits(runtime_settings: ApiSettings) -> None:
    if (
        runtime_settings.audit_verify_on_startup_strict
        and not runtime_settings.audit_sink_jsonl
    ):
        raise RuntimeError(
            "SENA_AUDIT_VERIFY_ON_STARTUP_STRICT=true requires SENA_AUDIT_SINK_JSONL"
        )
    if not (0 < runtime_settings.auto_recovery_error_threshold <= 1):
        raise RuntimeError("SENA_AUTO_RECOVERY_ERROR_THRESHOLD must be within (0, 1]")
    if runtime_settings.auto_recovery_window_seconds <= 0:
        raise RuntimeError("SENA_AUTO_RECOVERY_WINDOW_SECONDS must be > 0")
    validate_ingestion_queue_settings(runtime_settings)


def build_runtime_state(
    runtime_settings: ApiSettings,
    rules: list,
    metadata: PolicyBundleMetadata,
    policy_repo: SQLitePolicyBundleRepository | None,
) -> EngineState:
    state = EngineState(runtime_settings, rules, metadata, policy_repo)
    state.reliability_service = ReliabilityService(
        ingestion_queue=build_ingestion_queue_backend(runtime_settings)
    )
    if runtime_settings.webhook_mapping_config_path:
        from sena.integrations.webhook import (
            WebhookPayloadMapper,
            load_webhook_mapping_config,
        )

        mapping_config = load_webhook_mapping_config(
            runtime_settings.webhook_mapping_config_path
        )
        state.webhook_mapper = WebhookPayloadMapper(mapping_config)
    if runtime_settings.slack_bot_token and runtime_settings.slack_channel:
        from sena.integrations.slack import SlackClient

        state.slack_client = SlackClient(
            bot_token=runtime_settings.slack_bot_token,
            default_channel=runtime_settings.slack_channel,
        )
    if runtime_settings.jira_mapping_config_path:
        from sena.integrations.jira import (
            AllowAllJiraWebhookVerifier,
            JiraConnector,
            RotatingSharedSecretJiraWebhookVerifier,
            load_jira_mapping_config,
        )

        jira_secrets = tuple(
            item
            for item in (
                runtime_settings.jira_webhook_secret,
                runtime_settings.jira_webhook_secret_previous,
            )
            if item
        )
        verifier = (
            RotatingSharedSecretJiraWebhookVerifier(jira_secrets)
            if jira_secrets
            else AllowAllJiraWebhookVerifier()
        )
        delivery_client = None
        if runtime_settings.jira_write_back:
            from sena.integrations.jira_client import JiraRestClient

            delivery_client = JiraRestClient(
                base_url=runtime_settings.jira_base_url,
                username=runtime_settings.jira_username,
                api_token=runtime_settings.jira_api_token,
                oauth_token=runtime_settings.jira_oauth_token,
                approved_transition_id=runtime_settings.jira_transition_approved_id,
                blocked_transition_id=runtime_settings.jira_transition_blocked_id,
            )

        state.jira_connector = JiraConnector(
            config=load_jira_mapping_config(runtime_settings.jira_mapping_config_path),
            verifier=verifier,
            reliability_db_path=_resolve_connector_reliability_db_path(
                runtime_settings
            ),
            require_durable_reliability=runtime_settings.runtime_mode == "production",
            delivery_client=delivery_client,
            reliability_observer=state.metrics.connector_reliability_observer(
                connector="jira"
            ),
        )

    if runtime_settings.servicenow_mapping_config_path:
        from sena.integrations.servicenow import (
            AllowAllServiceNowWebhookVerifier,
            RotatingSharedSecretServiceNowWebhookVerifier,
            ServiceNowConnector,
            load_servicenow_mapping_config,
        )

        servicenow_secrets = tuple(
            item
            for item in (
                runtime_settings.servicenow_webhook_secret,
                runtime_settings.servicenow_webhook_secret_previous,
            )
            if item
        )
        verifier = (
            RotatingSharedSecretServiceNowWebhookVerifier(servicenow_secrets)
            if servicenow_secrets
            else AllowAllServiceNowWebhookVerifier()
        )
        delivery_client = None
        if runtime_settings.servicenow_write_back:
            from sena.integrations.servicenow_client import ServiceNowRestClient

            delivery_client = ServiceNowRestClient(
                base_url=runtime_settings.servicenow_base_url,
                username=runtime_settings.servicenow_username,
                password=runtime_settings.servicenow_password,
                oauth_token=runtime_settings.servicenow_oauth_token,
            )

        state.servicenow_connector = ServiceNowConnector(
            config=load_servicenow_mapping_config(
                runtime_settings.servicenow_mapping_config_path
            ),
            verifier=verifier,
            reliability_db_path=_resolve_connector_reliability_db_path(
                runtime_settings
            ),
            require_durable_reliability=runtime_settings.runtime_mode == "production",
            delivery_client=delivery_client,
            reliability_observer=state.metrics.connector_reliability_observer(
                connector="servicenow"
            ),
        )

    state.processing_service = ProductionProcessingService(state)
    if runtime_settings.auto_recovery_enabled:
        state.recovery_service = AutomaticRecoveryService(
            state=state,
            error_threshold=runtime_settings.auto_recovery_error_threshold,
            error_window_seconds=runtime_settings.auto_recovery_window_seconds,
        )
    state.dlq_worker = DeadLetterWorker(
        store=state.processing_store,
        processor=state.processing_service.process_event,
        alert_callback=lambda message: print(message),
    )
    state.connector_registry = _build_connector_registry(
        webhook=state.webhook_mapper,
        slack=state.slack_client,
        jira=state.jira_connector,
        servicenow=state.servicenow_connector,
    )
    return state


def build_api_key_roles(settings: ApiSettings) -> dict[str, str]:
    if settings.api_keys:
        return dict(settings.api_keys)
    if settings.api_key:
        return {settings.api_key: "admin"}
    return {}


def is_role_allowed(role: str, method: str, path: str) -> bool:
    if role == "admin":
        return True
    allowed = ROLE_ALLOWED_ENDPOINTS.get(role, set())
    if (method, path) in allowed:
        return True
    path_parts = path.strip("/").split("/")
    for allowed_method, allowed_path in allowed:
        if allowed_method != method:
            continue
        template_parts = allowed_path.strip("/").split("/")
        if len(template_parts) != len(path_parts):
            continue
        if all(
            template.startswith("{") and template.endswith("}") or template == actual
            for template, actual in zip(template_parts, path_parts)
        ):
            return True
    return False


def evaluate_abac_policy(
    *,
    role: str,
    environment: str,
    bundle_name: str | None,
    action_type: str | None,
    expected_bundle_name: str,
) -> tuple[bool, str | None]:
    if role == "admin":
        return True, None
    allowed_envs = ROLE_ALLOWED_ENVIRONMENTS.get(role)
    if allowed_envs is not None and environment not in allowed_envs:
        return False, f"role '{role}' is not permitted in environment '{environment}'"
    if bundle_name and bundle_name != expected_bundle_name:
        return (
            False,
            f"bundle '{bundle_name}' is not allowed for this key; expected '{expected_bundle_name}'",
        )
    denied_actions = ROLE_ACTION_TYPE_DENYLIST.get(role, set())
    if action_type and action_type in denied_actions:
        return False, f"action_type '{action_type}' is prohibited for role '{role}'"
    return True, None
