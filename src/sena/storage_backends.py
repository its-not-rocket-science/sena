from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StorageBackendCapability:
    concern: str
    backend: str
    concurrency_model: str
    durability_assumptions: str
    deployment_suitability: str
    notes: str


CAPABILITIES: dict[tuple[str, str], StorageBackendCapability] = {
    (
        "audit",
        "local_file",
    ): StorageBackendCapability(
        concern="audit",
        backend="local_file",
        concurrency_model="single-host file lock",
        durability_assumptions="local filesystem + append-only discipline; not WORM enforced",
        deployment_suitability="pilot",
        notes="Useful for local and pilot evidence capture. Not a compliant immutable archive.",
    ),
    (
        "audit",
        "sqlite_append_only",
    ): StorageBackendCapability(
        concern="audit",
        backend="sqlite_append_only",
        concurrency_model="single-writer sqlite transaction",
        durability_assumptions="sqlite WAL/FULL with append-only table triggers",
        deployment_suitability="pilot",
        notes="Improves append-only enforcement but remains single-node storage.",
    ),
    (
        "audit",
        "s3_object_lock",
    ): StorageBackendCapability(
        concern="audit",
        backend="s3_object_lock",
        concurrency_model="cloud object storage API",
        durability_assumptions="provider durability + Object Lock COMPLIANCE policy",
        deployment_suitability="production",
        notes="Production-intended immutable backend when object lock policy is enforced.",
    ),
    (
        "audit",
        "azure_immutable_blob",
    ): StorageBackendCapability(
        concern="audit",
        backend="azure_immutable_blob",
        concurrency_model="cloud blob API",
        durability_assumptions="provider durability + immutable retention policy",
        deployment_suitability="production",
        notes="Production-intended immutable backend when retention policy is validated.",
    ),
    (
        "policy_bundle",
        "filesystem",
    ): StorageBackendCapability(
        concern="policy_bundle",
        backend="filesystem",
        concurrency_model="host filesystem reads",
        durability_assumptions="bundles are static files deployed with service",
        deployment_suitability="pilot",
        notes="Good for local/pilot demos, but lacks central lifecycle and transactional promotions.",
    ),
    (
        "policy_bundle",
        "sqlite",
    ): StorageBackendCapability(
        concern="policy_bundle",
        backend="sqlite",
        concurrency_model="sqlite transactional single-host writes",
        durability_assumptions="WAL/FULL on attached disk",
        deployment_suitability="pilot",
        notes="Durable on one node but not a multi-node production registry backend.",
    ),
    (
        "integration_reliability",
        "sqlite",
    ): StorageBackendCapability(
        concern="integration_reliability",
        backend="sqlite",
        concurrency_model="sqlite transactional writes",
        durability_assumptions="single-node file durability",
        deployment_suitability="pilot",
        notes="Persistent idempotency and delivery outcomes for pilot usage.",
    ),
    (
        "integration_reliability",
        "inmemory",
    ): StorageBackendCapability(
        concern="integration_reliability",
        backend="inmemory",
        concurrency_model="process memory",
        durability_assumptions="none; process restart loses state",
        deployment_suitability="local_dev",
        notes="Development-only mode for connector tests.",
    ),
    (
        "runtime_processing",
        "sqlite",
    ): StorageBackendCapability(
        concern="runtime_processing",
        backend="sqlite",
        concurrency_model="sqlite atomic claim/replay",
        durability_assumptions="single-node file durability",
        deployment_suitability="pilot",
        notes="Includes idempotency responses, DLQ, and explanation cache state.",
    ),
    (
        "ingestion_queue",
        "memory",
    ): StorageBackendCapability(
        concern="ingestion_queue",
        backend="memory",
        concurrency_model="in-process queue",
        durability_assumptions="volatile memory only",
        deployment_suitability="pilot",
        notes="Fast local/pilot queue; events are lost on crash/restart.",
    ),
    (
        "ingestion_queue",
        "redis",
    ): StorageBackendCapability(
        concern="ingestion_queue",
        backend="redis",
        concurrency_model="networked queue via Redis",
        durability_assumptions="depends on Redis persistence and HA configuration",
        deployment_suitability="production",
        notes="Production-intended ingestion queue abstraction.",
    ),
}


def get_capability(concern: str, backend: str) -> StorageBackendCapability | None:
    return CAPABILITIES.get((concern, backend))
