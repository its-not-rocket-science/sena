from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sena.audit.evidentiary import export_evidence_bundle
from sena.audit.sinks import AuditSink, JsonlFileAuditSink
from sena.core.models import PolicyRule


def _resolve_sink(path_or_sink: str | AuditSink) -> AuditSink:
    if isinstance(path_or_sink, str):
        return JsonlFileAuditSink(path=path_or_sink)
    return path_or_sink


def _framework_for_control(control_id: str) -> str:
    prefix, sep, _ = control_id.partition(":")
    if sep and prefix:
        return prefix.strip().upper()
    return "CUSTOM"


def build_control_mapping(rules: list[PolicyRule]) -> dict[str, Any]:
    controls: dict[str, dict[str, Any]] = {}
    for rule in rules:
        for control_id in sorted(set(rule.control_ids)):
            entry = controls.setdefault(
                control_id,
                {
                    "control_id": control_id,
                    "framework": _framework_for_control(control_id),
                    "rules": [],
                },
            )
            entry["rules"].append(
                {
                    "rule_id": rule.id,
                    "description": rule.description,
                    "decision": rule.decision.value,
                    "inviolable": rule.inviolable,
                    "applies_to": list(rule.applies_to),
                }
            )

    return {
        "schema_version": "1",
        "controls": [controls[key] for key in sorted(controls)],
    }


def build_evidence_vault(
    path_or_sink: str | AuditSink,
    rules: list[PolicyRule],
) -> dict[str, Any]:
    sink = _resolve_sink(path_or_sink)
    records = sink.load_records()
    rule_index = {rule.id: rule for rule in rules}

    vault: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        matched_rule_ids = row.get("matched_rule_ids")
        if not isinstance(matched_rule_ids, list):
            continue
        for rule_id in matched_rule_ids:
            rule = rule_index.get(str(rule_id))
            if rule is None or not rule.control_ids:
                continue
            for control_id in sorted(set(rule.control_ids)):
                vault[control_id].append(
                    {
                        "decision_id": row.get("decision_id"),
                        "rule_id": rule.id,
                        "outcome": row.get("outcome"),
                        "event_timestamp": row.get("event_timestamp")
                        or row.get("timestamp"),
                        "storage_sequence_number": row.get("storage_sequence_number"),
                        "chain_hash": row.get("chain_hash"),
                    }
                )

    return {
        "schema_version": "1",
        "controls": [
            {
                "control_id": control_id,
                "framework": _framework_for_control(control_id),
                "decision_count": len(entries),
                "decisions": sorted(
                    entries,
                    key=lambda item: (
                        str(item.get("event_timestamp") or ""),
                        str(item.get("decision_id") or ""),
                    ),
                ),
            }
            for control_id, entries in sorted(vault.items())
        ],
    }


def export_control_audit_package(
    path_or_sink: str | AuditSink,
    rules: list[PolicyRule],
    control_id: str,
) -> dict[str, Any]:
    control_map = build_control_mapping(rules)
    vault = build_evidence_vault(path_or_sink, rules)

    selected_control = next(
        (
            item
            for item in control_map["controls"]
            if str(item.get("control_id")) == control_id
        ),
        None,
    )
    if selected_control is None:
        raise KeyError(f"control not found: {control_id}")

    evidence_for_control = next(
        (
            item
            for item in vault["controls"]
            if str(item.get("control_id")) == control_id
        ),
        {"control_id": control_id, "framework": _framework_for_control(control_id), "decisions": []},
    )

    evidence_bundles = []
    for decision in evidence_for_control.get("decisions", []):
        decision_id = str(decision.get("decision_id") or "")
        if not decision_id:
            continue
        evidence_bundles.append(export_evidence_bundle(path_or_sink, decision_id))

    return {
        "schema_version": "1",
        "artifact_schema": "sena.control_audit_package.v1",
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "control": selected_control,
        "evidence_vault_entry": evidence_for_control,
        "evidence_bundles": evidence_bundles,
    }
