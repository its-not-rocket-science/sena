from __future__ import annotations

from pathlib import Path

from sena.api.config import ApiSettings
from sena.services.reliability_service import (
    InMemoryIngestionQueue,
    RedisIngestionQueue,
    SQLiteIngestionQueue,
)


def validate_ingestion_queue_settings(settings: ApiSettings) -> None:
    if settings.ingestion_queue_backend not in {"memory", "redis", "sqlite"}:
        raise RuntimeError(
            "SENA_INGESTION_QUEUE_BACKEND must be one of ['memory', 'redis', 'sqlite']"
        )
    if settings.ingestion_queue_max_size <= 0:
        raise RuntimeError("SENA_INGESTION_QUEUE_MAX_SIZE must be > 0")
    if settings.ingestion_queue_backend == "redis" and not settings.ingestion_queue_redis_url:
        raise RuntimeError("SENA_INGESTION_QUEUE_REDIS_URL is required when backend is redis")
    if settings.runtime_mode in {"pilot", "production"} and settings.ingestion_queue_backend == "memory":
        raise RuntimeError(
            f"SENA_RUNTIME_MODE={settings.runtime_mode} forbids "
            "SENA_INGESTION_QUEUE_BACKEND=memory because queued inbound work "
            "must survive process restart. Configure redis or sqlite."
        )
    if settings.ingestion_queue_backend == "sqlite":
        sqlite_parent = Path(settings.processing_sqlite_path).expanduser().resolve().parent
        if not sqlite_parent.exists() or not sqlite_parent.is_dir():
            raise RuntimeError(
                "SENA_PROCESSING_SQLITE_PATH parent directory must exist when "
                "SENA_INGESTION_QUEUE_BACKEND=sqlite: "
                f"{settings.processing_sqlite_path}"
            )


def build_ingestion_queue_backend(settings: ApiSettings) -> object:
    if settings.ingestion_queue_backend == "redis":
        return RedisIngestionQueue(redis_url=str(settings.ingestion_queue_redis_url))
    if settings.ingestion_queue_backend == "sqlite":
        return SQLiteIngestionQueue(sqlite_path=settings.processing_sqlite_path)
    return InMemoryIngestionQueue(max_size=settings.ingestion_queue_max_size)
