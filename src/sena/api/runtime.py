from __future__ import annotations

from pathlib import Path
from typing import Any
from sena.api.config import ApiSettings
from sena.api.metrics import ApiMetrics
from sena.core.enums import DecisionOutcome
from sena.core.models import PolicyBundleMetadata
from sena.policy.parser import PolicyParseError, load_policy_bundle
from sena.policy.release_signing import verify_release_manifest
from sena.policy.store import SQLitePolicyBundleRepository
from sena.api.processing_store import DeadLetterWorker, ProcessingStore
from sena.services.production_processing_service import ProductionProcessingService

VALID_API_ROLES = {"admin", "policy_author", "evaluator"}
VALID_RUNTIME_MODES = {"development", "pilot", "production"}
VALID_POLICY_STORE_BACKENDS = {"filesystem", "sqlite"}
ROLE_ALLOWED_ENDPOINTS: dict[str, set[tuple[str, str]]] = {
    "policy_author": {
        ("POST", "/v1/bundle/register"),
        ("POST", "/v1/bundle/promote"),
        ("POST", "/v1/bundle/diff"),
        ("POST", "/v1/bundle/promotion/validate"),
        ("POST", "/v1/bundle/rollback"),
        ("GET", "/v1/bundles/history"),
        ("GET", "/v1/bundles/active"),
        ("GET", "/v1/bundles/by-version"),
    },
    "evaluator": {
        ("POST", "/v1/evaluate"),
        ("POST", "/v1/evaluate/review-package"),
        ("POST", "/v1/evaluate/batch"),
        ("POST", "/v1/integrations/webhook"),
        ("POST", "/v1/integrations/jira/webhook"),
        ("POST", "/v1/integrations/servicenow/webhook"),
        ("POST", "/v1/integrations/slack/interactions"),
        ("POST", "/v1/simulation"),
    },
}


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
        self.processing_store: ProcessingStore = ProcessingStore(settings.processing_sqlite_path)
        self.processing_service: ProductionProcessingService | None = None
        self.dlq_worker: DeadLetterWorker | None = None


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

    if runtime_settings.api_key and not runtime_settings.enable_api_key_auth:
        raise RuntimeError("SENA_API_KEY is set but SENA_API_KEY_ENABLED is not true")
    if (
        runtime_settings.runtime_mode == "production"
        and not runtime_settings.enable_api_key_auth
    ):
        raise RuntimeError(
            "SENA_RUNTIME_MODE=production requires SENA_API_KEY_ENABLED=true"
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
    if bool(runtime_settings.slack_bot_token) != bool(runtime_settings.slack_channel):
        raise RuntimeError(
            "SENA_SLACK_BOT_TOKEN and SENA_SLACK_CHANNEL must be set together when enabling Slack integration"
        )
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
        if runtime_settings.jira_mapping_config_path and not (
            runtime_settings.jira_webhook_secret
            or runtime_settings.jira_webhook_secret_previous
        ):
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production requires SENA_JIRA_WEBHOOK_SECRET (or SENA_JIRA_WEBHOOK_SECRET_PREVIOUS) when Jira integration is enabled"
            )
        if runtime_settings.servicenow_mapping_config_path and not (
            runtime_settings.servicenow_webhook_secret
            or runtime_settings.servicenow_webhook_secret_previous
        ):
            raise RuntimeError(
                "SENA_RUNTIME_MODE=production requires SENA_SERVICENOW_WEBHOOK_SECRET (or SENA_SERVICENOW_WEBHOOK_SECRET_PREVIOUS) when ServiceNow integration is enabled"
            )
    if (
        runtime_settings.audit_verify_on_startup_strict
        and not runtime_settings.audit_sink_jsonl
    ):
        raise RuntimeError(
            "SENA_AUDIT_VERIFY_ON_STARTUP_STRICT=true requires SENA_AUDIT_SINK_JSONL"
        )


def build_runtime_state(
    runtime_settings: ApiSettings,
    rules: list,
    metadata: PolicyBundleMetadata,
    policy_repo: SQLitePolicyBundleRepository | None,
) -> EngineState:
    state = EngineState(runtime_settings, rules, metadata, policy_repo)
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
            delivery_client=delivery_client,
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
            delivery_client=delivery_client,
        )


    state.processing_service = ProductionProcessingService(state)
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
    return (method, path) in ROLE_ALLOWED_ENDPOINTS.get(role, set())
