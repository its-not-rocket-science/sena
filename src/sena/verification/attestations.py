from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


VERIFIER_ROLE = "verifier"


@dataclass(frozen=True)
class DecisionAttestation:
    attestation_id: str
    decision_id: str
    decision_hash: str
    signer_id: str
    signer_role: str
    key_id: str
    signature: str
    signed_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "attestation_id": self.attestation_id,
            "decision_id": self.decision_id,
            "decision_hash": self.decision_hash,
            "signer_id": self.signer_id,
            "signer_role": self.signer_role,
            "key_id": self.key_id,
            "signature": self.signature,
            "signed_at": self.signed_at,
        }


def _canonical_signing_payload(
    *,
    decision_id: str,
    decision_hash: str,
    signer_id: str,
    signer_role: str,
    key_id: str,
    signed_at: str,
) -> bytes:
    payload = {
        "decision_hash": decision_hash,
        "decision_id": decision_id,
        "key_id": key_id,
        "signed_at": signed_at,
        "signer_id": signer_id,
        "signer_role": signer_role,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_attestation(
    *,
    decision_id: str,
    decision_hash: str,
    signer_id: str,
    signer_role: str,
    signing_key: str,
    key_id: str = "third_party_verifier",
    signed_at: str | None = None,
) -> DecisionAttestation:
    normalized_signed_at = signed_at or datetime.now(timezone.utc).isoformat()
    signing_payload = _canonical_signing_payload(
        decision_id=decision_id,
        decision_hash=decision_hash,
        signer_id=signer_id,
        signer_role=signer_role,
        key_id=key_id,
        signed_at=normalized_signed_at,
    )
    signature = hmac.new(
        key=signing_key.encode("utf-8"),
        msg=signing_payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return DecisionAttestation(
        attestation_id=f"att_{uuid.uuid4().hex[:12]}",
        decision_id=decision_id,
        decision_hash=decision_hash,
        signer_id=signer_id,
        signer_role=signer_role,
        key_id=key_id,
        signature=signature,
        signed_at=normalized_signed_at,
    )


def verify_attestation_signature(
    *,
    attestation: DecisionAttestation,
    decision_hash: str,
    signing_key: str,
) -> bool:
    expected = _canonical_signing_payload(
        decision_id=attestation.decision_id,
        decision_hash=decision_hash,
        signer_id=attestation.signer_id,
        signer_role=attestation.signer_role,
        key_id=attestation.key_id,
        signed_at=attestation.signed_at,
    )
    actual_signature = hmac.new(
        key=signing_key.encode("utf-8"),
        msg=expected,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(actual_signature, attestation.signature)
