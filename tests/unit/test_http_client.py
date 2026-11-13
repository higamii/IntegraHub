import httpx
import pytest

from integrahub.exceptions import (
    UpstreamConnectionError,
    UpstreamHTTPError,
    UpstreamInvalidResponseError,
    UpstreamTimeoutError,
)
from integrahub.http_client import ResilientHTTPClient, parse_retry_after
from integrahub.retry import RetryPolicy

URL = "https://api.example.test/data"


class Harness:
    """A client on a scripted transport that records requested sleeps."""

    def __init__(self, responses: list, *, max_attempts: int = 3) -> None:
        self.responses = list(responses)
        self.sleeps: list[float] = []
        self.calls = 0
        self.client = ResilientHTTPClient(
            timeout=1.0,
            connect_timeout=1.0,
            retry_policy=RetryPolicy(
                max_attempts=max_attempts, base_delay=0.1, max_delay=1.0, jitter=0.0
            ),
            transport=httpx.MockTransport(self._handle),
            sleep=self._sleep,
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("simulated", request=request)
        # Build a fresh response each time: the last scripted item repeats indefinitely.
        return httpx.Response(item.status_code, headers=item.headers, content=item.content)

    async def _sleep(self, delay: float) -> None:
        self.sleeps.append(delay)


@pytest.fixture
def make_harness():
    return Harness


async def test_returns_parsed_json_on_success(make_harness):
    harness = make_harness([httpx.Response(200, json={"ok": True})])
    try:
        result = await harness.client.get_json(URL, source="test")
    finally:
        await harness.client.aclose()

    assert result.data == {"ok": True}
    assert result.attempts == 1
    assert harness.sleeps == []


async def test_retries_transient_status_with_exponential_backoff(make_harness):
    harness = make_harness(
        [httpx.Response(503), httpx.Response(502), httpx.Response(200, json={"ok": 1})]
    )
    try:
        result = await harness.client.get_json(URL, source="test")
    finally:
        await harness.client.aclose()

    assert result.attempts == 3
    assert harness.calls == 3
    assert harness.sleeps == [0.1, 0.2]


async def test_gives_up_after_max_attempts(make_harness):
    harness = make_harness([httpx.Response(500)], max_attempts=3)
    try:
        with pytest.raises(UpstreamHTTPError) as excinfo:
            await harness.client.get_json(URL, source="test")
    finally:
        await harness.client.aclose()

    assert excinfo.value.status_code == 500
    assert excinfo.value.attempts == 3
    assert harness.calls == 3


async def test_client_errors_are_not_retried(make_harness):
    harness = make_harness([httpx.Response(404)])
    try:
        with pytest.raises(UpstreamHTTPError) as excinfo:
            await harness.client.get_json(URL, source="test")
    finally:
        await harness.client.aclose()

    assert excinfo.value.status_code == 404
    assert excinfo.value.attempts == 1
    assert harness.calls == 1
    assert harness.sleeps == []


async def test_retry_after_header_is_honoured(make_harness):
    harness = make_harness(
        [httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json={})]
    )
    try:
        await harness.client.get_json(URL, source="test")
    finally:
        await harness.client.aclose()

    assert harness.sleeps == [2.0]


async def test_timeouts_are_retried_then_reported(make_harness):
    harness = make_harness([httpx.ConnectTimeout], max_attempts=2)
    try:
        with pytest.raises(UpstreamTimeoutError) as excinfo:
            await harness.client.get_json(URL, source="test")
    finally:
        await harness.client.aclose()

    assert excinfo.value.attempts == 2
    assert harness.calls == 2


async def test_connection_errors_are_mapped(make_harness):
    harness = make_harness([httpx.ConnectError], max_attempts=2)
    try:
        with pytest.raises(UpstreamConnectionError):
            await harness.client.get_json(URL, source="test")
    finally:
        await harness.client.aclose()


async def test_invalid_json_is_not_retried(make_harness):
    harness = make_harness([httpx.Response(200, content=b"<html>not json</html>")])
    try:
        with pytest.raises(UpstreamInvalidResponseError):
            await harness.client.get_json(URL, source="test")
    finally:
        await harness.client.aclose()

    assert harness.calls == 1


async def test_github_style_rate_limit_is_fatal_and_explained(make_harness):
    harness = make_harness([httpx.Response(403, headers={"x-ratelimit-remaining": "0"})])
    try:
        with pytest.raises(UpstreamHTTPError, match="rate limit") as excinfo:
            await harness.client.get_json(URL, source="github")
    finally:
        await harness.client.aclose()

    assert excinfo.value.retryable is False
    assert harness.calls == 1


@pytest.mark.parametrize(
    ("header", "expected"),
    [("3", 3.0), (" 1.5 ", 1.5), ("0", 0.0), ("-1", None), ("soon", None), (None, None)],
)
def test_parse_retry_after(header, expected):
    assert parse_retry_after(header) == expected
