from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class LegalHoldStore:
    path: str

    def _path(self) -> Path:
        return Path(self.path)

    def _lock_path(self) -> Path:
        p = self._path()
        return p.with_name(f"{p.name}.lock")

    def _acquire_lock(self):
        import fcntl

        lock = self._lock_path()
        lock.parent.mkdir(parents=True, exist_ok=True)
        handle = lock.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    def _read(self) -> dict[str, Any]:
        p = self._path()
        if not p.exists():
            return {"holds": []}
        payload = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {"holds": []}
        holds = payload.get("holds", [])
        if not isinstance(holds, list):
            holds = []
        return {"holds": holds}

    def list_holds(self) -> list[dict[str, Any]]:
        return list(self._read()["holds"])

    def is_held(self, decision_id: str) -> bool:
        return any(str(item.get("decision_id")) == decision_id for item in self.list_holds())

    def create_hold(self, decision_id: str, reason: str | None = None) -> dict[str, Any]:
        lock_handle = self._acquire_lock()
        try:
            payload = self._read()
            for item in payload["holds"]:
                if str(item.get("decision_id")) == decision_id:
                    return item
            hold = {
                "decision_id": decision_id,
                "reason": reason or "legal_hold",
                "held_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            payload["holds"].append(hold)
            self._path().parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path().with_suffix(self._path().suffix + ".tmp")
            tmp.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
            os.replace(tmp, self._path())
            return hold
        finally:
            lock_handle.close()


def hold_store_from_audit_path(audit_path: str | None) -> LegalHoldStore | None:
    if audit_path is None:
        return None
    base = Path(audit_path)
    return LegalHoldStore(path=str(base.with_name(f"{base.name}.holds.json")))
