from __future__ import annotations

from pathlib import Path

from sena.integrations.base import IntegrationError
from sena.integrations.persistence import SQLiteIntegrationReliabilityStore


def resolve_durable_reliability_store(
    *,
    reliability_store: SQLiteIntegrationReliabilityStore | None,
    reliability_db_path: str | None,
    require_durable_reliability: bool,
    error_cls: type[IntegrationError],
) -> SQLiteIntegrationReliabilityStore | None:
    if reliability_store is not None and reliability_db_path:
        raise error_cls(
            "configure exactly one durability source: reliability_store or reliability_db_path"
        )
    durable_store = reliability_store
    if durable_store is None and reliability_db_path:
        durable_store = SQLiteIntegrationReliabilityStore(str(Path(reliability_db_path)))
    if require_durable_reliability and durable_store is None:
        raise error_cls(
            "durable reliability storage is required; "
            "configure reliability_store or reliability_db_path"
        )
    return durable_store
