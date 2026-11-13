"""Structured (JSON) logging configuration using only the standard library."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

#: Correlation id of the request being handled (set by the HTTP middleware).
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_HANDLER_NAME = "integrahub"
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _RESERVED and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """Render each log record as a single JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-friendly formatter for local development (extras as ``key=value``)."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = _extra_fields(record)
        request_id = request_id_var.get()
        if request_id:
            extras = {"request_id": request_id, **extras}
        if extras:
            line += " | " + " ".join(f"{key}={value}" for key, value in extras.items())
        return line


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Configure the root logger. Safe to call more than once."""
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if h.get_name() != _HANDLER_NAME]

    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter() if json_output else ConsoleFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Route uvicorn's own logs through our handler; request logs come from our middleware.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False

    # Keep HTTP client libraries quiet unless something goes wrong.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
