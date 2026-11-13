import io
import json
import logging

import pytest

from integrahub.logging_config import (
    ConsoleFormatter,
    JsonFormatter,
    configure_logging,
    request_id_var,
)


@pytest.fixture
def capture():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("integrahub.test.logging")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    yield logger, handler, stream
    logger.handlers = []


def test_json_formatter_emits_one_json_object_with_extras(capture):
    logger, handler, stream = capture
    handler.setFormatter(JsonFormatter())

    token = request_id_var.set("req-123")
    try:
        logger.info("sync done", extra={"integration": "github", "attempts": 2})
    finally:
        request_id_var.reset(token)

    entry = json.loads(stream.getvalue())
    assert entry["message"] == "sync done"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "integrahub.test.logging"
    assert entry["integration"] == "github"
    assert entry["attempts"] == 2
    assert entry["request_id"] == "req-123"
    assert entry["timestamp"].endswith("+00:00")


def test_json_formatter_includes_exception_traceback(capture):
    logger, handler, stream = capture
    handler.setFormatter(JsonFormatter())

    try:
        1 / 0
    except ZeroDivisionError:
        logger.exception("boom")

    entry = json.loads(stream.getvalue())
    assert "ZeroDivisionError" in entry["exception"]


def test_console_formatter_appends_extras(capture):
    logger, handler, stream = capture
    handler.setFormatter(ConsoleFormatter())

    logger.info("hello", extra={"integration": "github"})

    assert "hello" in stream.getvalue()
    assert "integration=github" in stream.getvalue()


def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        configure_logging("INFO", json_output=True)
        configure_logging("DEBUG", json_output=False)

        ours = [h for h in root.handlers if h.get_name() == "integrahub"]
        assert len(ours) == 1
        assert isinstance(ours[0].formatter, ConsoleFormatter)
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
