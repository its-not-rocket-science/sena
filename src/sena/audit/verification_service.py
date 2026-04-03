from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

from sena.audit.chain import verify_audit_chain
from sena.audit.merkle import build_merkle_tree, get_proof, verify_proof
from sena.audit.sinks import JsonlFileAuditSink


@dataclass
class AuditVerificationReport:
    passed: bool
    checked_records: int
    chain_valid: bool
    merkle_valid: bool
    errors: list[str]
    report_path: str


class DailyAuditVerificationService:
    def __init__(self, audit_path: str, metrics: Any | None = None) -> None:
        self.audit_path = audit_path
        self.metrics = metrics

    def run_once(self) -> AuditVerificationReport:
        chain = verify_audit_chain(self.audit_path)
        sink = JsonlFileAuditSink(path=self.audit_path)
        rows = sink.load_records()
        errors: list[str] = []
        merkle_valid = True

        if rows:
            tree = build_merkle_tree(rows)
            for idx, entry in enumerate(rows):
                proof = get_proof(tree, idx)
                if not verify_proof(entry, proof, tree.root):
                    merkle_valid = False
                    errors.append(f"merkle_proof_invalid:record_index={idx + 1}")
        else:
            merkle_valid = False
            errors.append("no_records")

        if not chain.get("valid", False):
            errors.extend(list(chain.get("errors", [])))

        passed = bool(chain.get("valid", False)) and merkle_valid

        report_dir = Path(os.getenv("SENA_AUDIT_VERIFY_REPORT_DIR", "/var/log/sena"))
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"audit-verify-{date.today().isoformat()}.json"
        payload = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "audit_path": self.audit_path,
            "passed": passed,
            "chain_valid": chain.get("valid", False),
            "checked_records": len(rows),
            "merkle_valid": merkle_valid,
            "errors": errors,
        }
        report_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

        if self.metrics is not None:
            self.metrics.observe_audit_verification_passed(passed=passed)

        if not passed:
            self._notify_failure_webhook(payload)

        return AuditVerificationReport(
            passed=passed,
            checked_records=len(rows),
            chain_valid=bool(chain.get("valid", False)),
            merkle_valid=merkle_valid,
            errors=errors,
            report_path=str(report_path),
        )

    def _notify_failure_webhook(self, payload: dict[str, Any]) -> None:
        endpoint = os.getenv("SENA_AUDIT_VERIFY_ALERT_WEBHOOK")
        if not endpoint:
            return
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        req = request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=5):  # nosec B310
            return

    def start_daily_thread(self) -> threading.Thread:
        interval_seconds = int(os.getenv("SENA_AUDIT_VERIFY_INTERVAL_SECONDS", "86400"))

        def _loop() -> None:
            while True:
                try:
                    self.run_once()
                except Exception:
                    pass
                threading.Event().wait(interval_seconds)

        thread = threading.Thread(target=_loop, daemon=True, name="sena-audit-verify")
        thread.start()
        return thread
