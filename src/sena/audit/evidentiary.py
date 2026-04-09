from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sena.audit.sinks import AuditSink, JsonlFileAuditSink


@dataclass(frozen=True)
class SymmetricSigningKey:
    key_id: str
    signer_identity: str
    secret: str


@dataclass(frozen=True)
class AuditRecordSigner:
    keys: tuple[SymmetricSigningKey, ...]

    def key_for_timestamp(self, timestamp_rfc3339: str) -> SymmetricSigningKey:
        if not self.keys:
            raise ValueError("at least one signing key is required")
        day_seed = timestamp_rfc3339[:10]
        digest = hashlib.sha256(day_seed.encode("utf-8")).hexdigest()
        idx = int(digest[:8], 16) % len(self.keys)
        return self.keys[idx]


@dataclass(frozen=True)
class AuditRecordVerifier:
    keyring: dict[str, SymmetricSigningKey]

    @classmethod
    def from_signer(cls, signer: AuditRecordSigner) -> "AuditRecordVerifier":
        return cls(keyring={item.key_id: item for item in signer.keys})


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def utc_now_rfc3339() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _digest_material(payload: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "chain_hash",
        "previous_chain_hash",
        "storage_sequence_number",
        "write_timestamp",
        "signature",
        "record_digest",
        "signed_timestamp_hash",
        "signing_key_id",
        "signer_identity",
    }
    return {k: v for k, v in payload.items() if k not in excluded}


def _record_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(_digest_material(payload)).encode("utf-8")).hexdigest()


def signable_material(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": payload.get("decision_id"),
        "policy_version": payload.get("policy_version")
        or payload.get("policy_bundle_release_id"),
        "event_timestamp": payload.get("event_timestamp"),
        "signed_timestamp_hash": payload.get("signed_timestamp_hash"),
        "record_digest": payload.get("record_digest"),
        "signing_key_id": payload.get("signing_key_id"),
        "signer_identity": payload.get("signer_identity"),
        "decision_output": payload.get("decision") or payload.get("outcome"),
        "input_payload": payload.get("input_payload") or payload.get("action"),
    }


def attach_evidentiary_fields(
    payload: dict[str, Any],
    signer: AuditRecordSigner,
    *,
    timestamp_rfc3339: str | None = None,
) -> dict[str, Any]:
    line = dict(payload)
    timestamp = timestamp_rfc3339 or utc_now_rfc3339()
    line["event_timestamp"] = timestamp
    line["record_digest"] = _record_digest(line)
    line["signed_timestamp_hash"] = hashlib.sha256(
        f"{timestamp}|{line['record_digest']}".encode("utf-8")
    ).hexdigest()
    key = signer.key_for_timestamp(timestamp)
    line["signer_identity"] = key.signer_identity
    line["signing_key_id"] = key.key_id
    signature = hmac.new(
        key.secret.encode("utf-8"),
        _canonical_json(signable_material(line)).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    line["signature"] = base64.b64encode(signature).decode("ascii")
    return line


def verify_signature(payload: dict[str, Any], verifier: AuditRecordVerifier) -> tuple[bool, str | None]:
    key_id = str(payload.get("signing_key_id") or "")
    key = verifier.keyring.get(key_id)
    if key is None:
        return False, f"unknown_signing_key:{key_id}"
    signature_b64 = str(payload.get("signature") or "")
    if not signature_b64:
        return False, "missing_signature"
    expected = hmac.new(
        key.secret.encode("utf-8"),
        _canonical_json(signable_material(payload)).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    actual = base64.b64decode(signature_b64.encode("ascii"))
    if not hmac.compare_digest(expected, actual):
        return False, "signature_mismatch"
    if payload.get("signer_identity") != key.signer_identity:
        return False, "signer_identity_mismatch"
    timestamp = str(payload.get("event_timestamp") or "")
    recomputed_record_digest = _record_digest(payload)
    if recomputed_record_digest != payload.get("record_digest"):
        return False, "record_digest_mismatch"
    expected_ts_hash = hashlib.sha256(
        f"{timestamp}|{recomputed_record_digest}".encode("utf-8")
    ).hexdigest()
    if expected_ts_hash != payload.get("signed_timestamp_hash"):
        return False, "timestamp_hash_mismatch"
    return True, None


def load_signer_from_keyring_file(path: str | Path) -> AuditRecordSigner:
    keyring = json.loads(Path(path).read_text(encoding="utf-8"))
    keys = tuple(
        SymmetricSigningKey(
            key_id=item["key_id"],
            signer_identity=item["signer_identity"],
            secret=item["secret"],
        )
        for item in keyring["keys"]
    )
    return AuditRecordSigner(keys=keys)


def _resolve_sink(path_or_sink: str | AuditSink) -> AuditSink:
    if isinstance(path_or_sink, str):
        return JsonlFileAuditSink(path=path_or_sink)
    return path_or_sink


def export_evidence_bundle(path_or_sink: str | AuditSink, decision_id: str) -> dict[str, Any]:
    sink = _resolve_sink(path_or_sink)
    records = sink.load_records()
    for row in records:
        if str(row.get("decision_id")) != decision_id:
            continue
        return {
            "schema_version": "1",
            "decision_id": decision_id,
            "input_payload": row.get("input_payload") or row.get("action") or {},
            "policy_version": row.get("policy_version")
            or row.get("policy_bundle_release_id"),
            "decision_output": row.get("decision") or row.get("outcome"),
            "signature": {
                "value": row.get("signature"),
                "signer_identity": row.get("signer_identity"),
                "signing_key_id": row.get("signing_key_id"),
            },
            "timestamp": {
                "rfc3339": row.get("event_timestamp"),
                "signed_timestamp_hash": row.get("signed_timestamp_hash"),
            },
            "hash_chain_proof": {
                "storage_sequence_number": row.get("storage_sequence_number"),
                "previous_chain_hash": row.get("previous_chain_hash"),
                "chain_hash": row.get("chain_hash"),
            },
        }
    raise KeyError(f"decision not found: {decision_id}")
