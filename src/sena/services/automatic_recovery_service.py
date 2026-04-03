from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib import request

from sena.services.audit_service import AuditService


@dataclass
class AutomaticRecoveryService:
    state: Any
    error_window_seconds: int = 300
    error_threshold: float = 0.10
    evaluation_paths: tuple[str, ...] = ("/v1/evaluate", "/v1/evaluate/batch", "/v1/evaluate/review-package")
    check_interval_seconds: int = 15
    _events: deque[tuple[float, int]] = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _thread: threading.Thread | None = None
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _last_recovery_at: float = 0.0

    def record(self, *, path: str, status_code: int) -> None:
        if not any(path.startswith(item) for item in self.evaluation_paths):
            return
        now = time.time()
        with self._lock:
            self._events.append((now, status_code))
            self._trim_locked(now)

    def start(self) -> None:
        if self._thread is not None:
            return

        def _loop() -> None:
            while not self._stop_event.wait(self.check_interval_seconds):
                try:
                    self._check_once()
                except Exception:
                    continue

        self._thread = threading.Thread(target=_loop, daemon=True, name="sena-auto-recovery")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _check_once(self) -> None:
        now = time.time()
        with self._lock:
            self._trim_locked(now)
            total = len(self._events)
            errors = sum(1 for _, code in self._events if code >= 400)
        if total == 0:
            return
        error_rate = errors / total
        if error_rate <= self.error_threshold:
            return
        if now - self._last_recovery_at < self.error_window_seconds:
            return
        recovery = self._trigger_recovery(error_rate=error_rate, errors=errors, total=total)
        if recovery:
            self._last_recovery_at = now

    def _trigger_recovery(self, *, error_rate: float, errors: int, total: int) -> bool:
        repo = self.state.policy_repo
        if repo is None:
            return False
        active = repo.get_active_bundle(self.state.settings.bundle_name)
        if active is None:
            return False
        history = repo.get_history(self.state.settings.bundle_name)
        previous_id = None
        for entry in history:
            if int(entry.get("bundle_id", -1)) != active.id:
                continue
            replaced = entry.get("replaced_bundle_id")
            if replaced is not None:
                previous_id = int(replaced)
                break
        if previous_id is None:
            return False
        repo.rollback_bundle(
            self.state.settings.bundle_name,
            previous_id,
            promoted_by="auto-recovery",
            promotion_reason=(
                f"Automatic recovery triggered: error_rate={error_rate:.3f} over "
                f"{self.error_window_seconds}s ({errors}/{total})"
            ),
            validation_artifact="automatic-recovery",
        )
        new_active = repo.get_active_bundle(self.state.settings.bundle_name)
        if new_active is not None:
            self.state.rules = new_active.rules
            self.state.metadata = new_active.metadata
            self.state.metrics.observe_active_policies(count=len(new_active.rules))

        audit_path = self.state.settings.audit_sink_jsonl
        if audit_path:
            AuditService(audit_path).append_record(
                {
                    "event_type": "policy.automatic_recovery",
                    "bundle_name": self.state.settings.bundle_name,
                    "rolled_back_to_bundle_id": previous_id,
                    "trigger_error_rate": round(error_rate, 5),
                    "trigger_window_seconds": self.error_window_seconds,
                    "trigger_errors": errors,
                    "trigger_total": total,
                    "triggered_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        self._send_alert(
            {
                "event": "policy.automatic_recovery",
                "bundle_name": self.state.settings.bundle_name,
                "rolled_back_to_bundle_id": previous_id,
                "error_rate": error_rate,
                "window_seconds": self.error_window_seconds,
                "errors": errors,
                "total": total,
            }
        )
        return True

    def _send_alert(self, payload: dict[str, Any]) -> None:
        endpoint = self.state.settings.auto_recovery_alert_webhook
        if not endpoint:
            return
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        req = request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=5):  # nosec B310
            return

    def _trim_locked(self, now: float) -> None:
        cutoff = now - self.error_window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
