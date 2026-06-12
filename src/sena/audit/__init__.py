"""Tamper-evident audit chain utilities and pluggable sinks."""

from sena.audit.chain import append_audit_record, compute_chain_hash, verify_audit_chain
from sena.audit.evidentiary import (
    AuditRecordSigner,
    AuditRecordVerifier,
    SymmetricSigningKey,
    export_evidence_bundle,
    load_signer_from_keyring_file,
)
from sena.audit.archive import (
    create_audit_archive,
    restore_audit_archive,
    verify_audit_archive,
)
from sena.audit.merkle import MerkleTree, build_merkle_tree, get_proof, verify_proof
from sena.audit.sinks import (
    AuditSink,
    AuditSinkError,
    JsonlFileAuditSink,
    RetentionPolicy,
    RotationPolicy,
    S3CompatibleAuditSink,
)

__all__ = [
    "AuditSink",
    "AuditSinkError",
    "JsonlFileAuditSink",
    "RetentionPolicy",
    "RotationPolicy",
    "S3CompatibleAuditSink",
    "append_audit_record",
    "compute_chain_hash",
    "create_audit_archive",
    "restore_audit_archive",
    "verify_audit_archive",
    "verify_audit_chain",
    "SymmetricSigningKey",
    "AuditRecordSigner",
    "AuditRecordVerifier",
    "load_signer_from_keyring_file",
    "export_evidence_bundle",
    "MerkleTree",
    "build_merkle_tree",
    "get_proof",
    "verify_proof",
]
