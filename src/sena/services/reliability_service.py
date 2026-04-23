from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Protocol


class QueueOverflowError(RuntimeError):
    """Raised when ingestion buffers are full and cannot accept more work."""


class CircuitBreakerOpenError(RuntimeError):
    """Raised when a dependency is short-circuited due to repeated failures."""


class IngestionQueueBackend(Protocol):
    def enqueue(self, event: dict[str, Any]) -> int: ...
    def pop(self) -> dict[str, Any] | None: ...
    def depth(self) -> int: ...


@dataclass(frozen=True)
class SLODefinition:
    name: str
    target: str
    measurement_window: str
    description: str


DEFAULT_SLOS: tuple[SLODefinition, ...] = (
    SLODefinition(
        name="api_latency_p95",
        target="<=250ms",
        measurement_window="rolling 28 days",
        description="95th percentile latency for /v1/evaluate and integration endpoints.",
    ),
    SLODefinition(
        name="api_availability",
        target=">=99.95%",
        measurement_window="rolling 28 days",
        description="Successful non-5xx responses for policy evaluation traffic.",
    ),
    SLODefinition(
        name="decision_durability",
        target=">=99.99%",
        measurement_window="rolling 28 days",
        description="Accepted events durably persisted to queue or dead-letter queue.",
    ),
)


class InMemoryIngestionQueue:
    """Deterministic in-memory queue used to buffer inbound events before processing."""

    def __init__(self, *, max_size: int = 1000) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be > 0")
        self._max_size = max_size
        self._items: deque[dict[str, Any]] = deque()
        self._lock = threading.Lock()

    def enqueue(self, event: dict[str, Any]) -> int:
        with self._lock:
            if len(self._items) >= self._max_size:
                raise QueueOverflowError(
                    f"ingestion queue is full (max_size={self._max_size})"
                )
            self._items.append(dict(event))
            return len(self._items)

    def pop(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._items:
                return None
            return self._items.popleft()

    def depth(self) -> int:
        with self._lock:
            return len(self._items)


class RedisIngestionQueue:
    """Optional Redis-backed queue for ingestion buffering.

    Requires `redis` extra dependency at runtime only when configured.
    """

    def __init__(self, *, redis_url: str, key: str = "sena:ingestion:queue") -> None:
        if not redis_url:
            raise ValueError("redis_url is required for redis queue backend")
        try:
            from redis import Redis
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError(
                "redis queue backend requires 'redis' package to be installed"
            ) from exc
        self._redis = Redis.from_url(redis_url)
        self._key = key

    def enqueue(self, event: dict[str, Any]) -> int:
        import json

        encoded = json.dumps(event, sort_keys=True)
        return int(self._redis.rpush(self._key, encoded))

    def pop(self) -> dict[str, Any] | None:
        import json

        raw = self._redis.lpop(self._key)
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8"))

    def depth(self) -> int:
        return int(self._redis.llen(self._key))


class SQLiteIngestionQueue:
    """Durable SQLite-backed queue for inbound event ingestion."""

    def __init__(self, *, sqlite_path: str) -> None:
        if not sqlite_path:
            raise ValueError("sqlite_path is required for sqlite queue backend")
        path = Path(sqlite_path).expanduser().resolve()
        parent = path.parent
        if not parent.exists() or not parent.is_dir():
            raise ValueError(
                "sqlite queue backend parent directory must exist: "
                f"{sqlite_path}"
            )
        self._db_path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = FULL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def enqueue(self, event: dict[str, Any]) -> int:
        encoded = json.dumps(event, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ingestion_queue (payload_json) VALUES (?)", (encoded,)
            )
            row = conn.execute("SELECT COUNT(*) AS count FROM ingestion_queue").fetchone()
            return int(row["count"]) if row is not None else 0

    def pop(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, payload_json FROM ingestion_queue ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute("DELETE FROM ingestion_queue WHERE id = ?", (int(row["id"]),))
            conn.execute("COMMIT")
            return json.loads(str(row["payload_json"]))

    def depth(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM ingestion_queue").fetchone()
            return int(row["count"]) if row is not None else 0


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0
    _state: str = "closed"
    _failure_count: int = 0
    _opened_at: float | None = None

    def _now(self) -> float:
        return time.monotonic()

    def allow_request(self) -> bool:
        if self._state != "open":
            return True
        if self._opened_at is None:
            return False
        if (self._now() - self._opened_at) >= self.recovery_timeout_seconds:
            self._state = "half_open"
            return True
        return False

    def record_success(self) -> None:
        self._state = "closed"
        self._failure_count = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._state = "open"
            self._opened_at = self._now()

    @property
    def state(self) -> str:
        return self._state


class ReliabilityService:
    """Coordinates ingestion queueing, circuit breakers, and graceful fallbacks."""

    def __init__(
        self,
        *,
        ingestion_queue: IngestionQueueBackend,
        circuit_breakers: dict[str, CircuitBreaker] | None = None,
    ) -> None:
        self.ingestion_queue = ingestion_queue
        self.circuit_breakers = circuit_breakers or {
            "jira": CircuitBreaker(),
            "servicenow": CircuitBreaker(),
            "webhook": CircuitBreaker(),
        }

    def enqueue_event(self, event: dict[str, Any]) -> int:
        return int(self.ingestion_queue.enqueue(event))

    def process_next(self, processor: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        event = self.ingestion_queue.pop()
        if event is None:
            return {"status": "empty"}
        return processor(event)

    def call_dependency(
        self,
        *,
        dependency_name: str,
        operation: Callable[[], dict[str, Any]],
        fallback: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        breaker = self.circuit_breakers.setdefault(dependency_name, CircuitBreaker())
        if not breaker.allow_request():
            return fallback("circuit_open")
        try:
            payload = operation()
        except Exception:
            breaker.record_failure()
            return fallback("dependency_failure")
        breaker.record_success()
        return payload

    def slo_payload(self) -> dict[str, Any]:
        return {
            "slo_definitions": [
                {
                    "name": item.name,
                    "target": item.target,
                    "measurement_window": item.measurement_window,
                    "description": item.description,
                }
                for item in DEFAULT_SLOS
            ]
        }
