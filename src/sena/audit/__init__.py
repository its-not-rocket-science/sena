"""Tamper-evident audit chain utilities and pluggable sinks."""

from sena.audit.chain import append_audit_record, compute_chain_hash, verify_audit_chain
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
    "verify_audit_chain",
]
