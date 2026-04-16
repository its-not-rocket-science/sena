from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

try:  # pragma: no cover - optional dependency path
    import structlog as _structlog
except ModuleNotFoundError:  # pragma: no cover - default in minimal installs
    _structlog = None

_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
_trace_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id", default=None
)
_span_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "span_id", default=None
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "module": record.module,
            "message": record.getMessage(),
            "request_id": _request_id_ctx.get(),
            "trace_id": _trace_id_ctx.get(),
            "span_id": _span_id_ctx.get(),
        }
        for field_name in (
            "method",
            "path",
            "status_code",
            "duration_ms",
            "error_code",
            "decision_id",
            "outcome",
            "policy_bundle",
            "evaluation_ms",
            "endpoint",
            "errors",
            "connector",
            "provider",
            "event_type",
            "action",
            "target",
            "delivery_id",
            "dead_letter_id",
            "note",
            "applied_exception_count",
            "job_id",
            "job_type",
            "job_status",
        ):
            if hasattr(record, field_name):
                payload[field_name] = getattr(record, field_name)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if root.handlers:
        return

    if _structlog is not None:
        timestamper = _structlog.processors.TimeStamper(
            fmt="iso", utc=True, key="timestamp"
        )
        shared_processors = [
            _structlog.contextvars.merge_contextvars,
            _structlog.stdlib.add_log_level,
            _structlog.processors.CallsiteParameterAdder(
                [_structlog.processors.CallsiteParameter.MODULE]
            ),
            timestamper,
            _structlog.processors.EventRenamer("message"),
        ]
        formatter = _structlog.stdlib.ProcessorFormatter(
            processor=_structlog.processors.JSONRenderer(),
            foreign_pre_chain=shared_processors,
        )
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        root.addHandler(handler)
        root.setLevel(level)
        _structlog.configure(
            processors=[
                _structlog.contextvars.merge_contextvars,
                _structlog.stdlib.add_log_level,
                _structlog.processors.CallsiteParameterAdder(
                    [_structlog.processors.CallsiteParameter.MODULE]
                ),
                timestamper,
                _structlog.processors.EventRenamer("message"),
                _structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=_structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


class _StdlibJsonLogger:
    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def info(self, event: str, **fields: Any) -> None:
        self._logger.info(event, extra=fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._logger.warning(event, extra=fields)

    def exception(self, event: str, **fields: Any) -> None:
        self._logger.exception(event, extra=fields)


def get_logger(name: str):
    if _structlog is not None:
        return _structlog.get_logger(name)
    return _StdlibJsonLogger(name)


def bind_request_context(
    *, request_id: str, trace_id: str | None = None, span_id: str | None = None
) -> None:
    _request_id_ctx.set(request_id)
    _trace_id_ctx.set(trace_id)
    _span_id_ctx.set(span_id)
    if _structlog is not None:
        _structlog.contextvars.clear_contextvars()
        _structlog.contextvars.bind_contextvars(
            request_id=request_id, trace_id=trace_id, span_id=span_id
        )


def clear_request_context() -> None:
    _request_id_ctx.set(None)
    _trace_id_ctx.set(None)
    _span_id_ctx.set(None)
    if _structlog is not None:
        _structlog.contextvars.clear_contextvars()
