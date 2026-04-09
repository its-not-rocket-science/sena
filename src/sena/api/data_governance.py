from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SENSITIVE_FIELD_NAMES = {
    "password",
    "passcode",
    "secret",
    "api_key",
    "token",
    "ssn",
    "social_security_number",
    "credit_card",
    "card_number",
    "iban",
    "routing_number",
    "account_number",
    "email",
    "phone",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
US_SSN_RE = re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b")
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


@dataclass(frozen=True)
class TenancyContext:
    tenant_id: str
    region: str


@dataclass(frozen=True)
class PiiScanResult:
    flagged_fields: tuple[str, ...]
    redacted_payload: dict[str, Any]


def _looks_sensitive_value(value: str) -> bool:
    return bool(
        EMAIL_RE.search(value) or US_SSN_RE.search(value) or CREDIT_CARD_RE.search(value)
    )


def scan_and_redact_payload(payload: dict[str, Any]) -> PiiScanResult:
    flagged: set[str] = set()

    def _walk(node: Any, *, path: str) -> Any:
        if isinstance(node, dict):
            redacted: dict[str, Any] = {}
            for key, value in node.items():
                normalized = key.strip().lower()
                field_path = f"{path}.{key}" if path else key
                if normalized in SENSITIVE_FIELD_NAMES:
                    flagged.add(field_path)
                    redacted[key] = "[REDACTED]"
                    continue
                redacted[key] = _walk(value, path=field_path)
            return redacted
        if isinstance(node, list):
            return [_walk(item, path=f"{path}[]") for item in node]
        if isinstance(node, str) and _looks_sensitive_value(node):
            flagged.add(path or "value")
            return "[REDACTED]"
        return node

    redacted_payload = _walk(payload, path="")
    if not isinstance(redacted_payload, dict):
        redacted_payload = {"value": redacted_payload}
    return PiiScanResult(
        flagged_fields=tuple(sorted(flagged)),
        redacted_payload=redacted_payload,
    )
