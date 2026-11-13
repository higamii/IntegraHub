"""Resilient HTTP client: timeouts, retries with exponential backoff, error mapping."""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from integrahub.exceptions import (
    UpstreamConnectionError,
    UpstreamError,
    UpstreamHTTPError,
    UpstreamInvalidResponseError,
    UpstreamTimeoutError,
)
from integrahub.retry import RetryPolicy, retry_async

logger = logging.getLogger(__name__)

#: Statuses that usually indicate a transient condition worth retrying.
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

QueryParams = Mapping[str, str | int | float]


@dataclass(frozen=True)
class HTTPResult:
    """Parsed JSON body plus how many HTTP attempts it took."""

    data: Any
    attempts: int
    elapsed_ms: int


def parse_retry_after(value: str | None) -> float | None:
    """Parse a numeric ``Retry-After`` header (seconds). HTTP-date values are ignored."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _retry_after_hint(exc: Exception) -> float | None:
    return exc.retry_after if isinstance(exc, UpstreamError) else None


class ResilientHTTPClient:
    """Thin wrapper around ``httpx.AsyncClient`` for fetching JSON from external APIs.

    * Explicit connect/read timeouts.
    * Retries timeouts, connection errors and transient HTTP statuses (429, 5xx) with
      exponential backoff + jitter, honouring ``Retry-After``.
    * Fails fast on other 4xx errors and on invalid JSON.
    * Every failure is mapped to a subclass of ``UpstreamError``.
    """

    def __init__(
        self,
        *,
        timeout: float,
        connect_timeout: float,
        retry_policy: RetryPolicy,
        transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str = "IntegraHub/0.1 (+https://github.com/higamii/integrahub)",
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._policy = retry_policy
        self._sleep = sleep
        self._rng = rng
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            transport=transport,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_json(
        self,
        url: str,
        *,
        params: QueryParams | None = None,
        headers: Mapping[str, str] | None = None,
        source: str = "upstream",
    ) -> HTTPResult:
        """GET ``url`` and return the decoded JSON body.

        Raises:
            UpstreamError: (a subclass) once retries are exhausted or the failure is fatal.
        """
        started = time.perf_counter()
        attempts = 0

        async def once(attempt: int) -> Any:
            nonlocal attempts
            attempts = attempt
            return await self._request_once(url, params, headers, source)

        def on_retry(attempt: int, exc: Exception, delay: float) -> None:
            logger.warning(
                "upstream request failed, retrying",
                extra={
                    "integration": source,
                    "attempt": attempt,
                    "max_attempts": self._policy.max_attempts,
                    "retry_in_seconds": round(delay, 3),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )

        try:
            data = await retry_async(
                once,
                policy=self._policy,
                should_retry=lambda exc: isinstance(exc, UpstreamError) and exc.retryable,
                get_retry_after=_retry_after_hint,
                on_retry=on_retry,
                sleep=self._sleep,
                rng=self._rng,
            )
        except UpstreamError as exc:
            exc.attempts = attempts
            raise
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return HTTPResult(data=data, attempts=attempts, elapsed_ms=elapsed_ms)

    async def _request_once(
        self,
        url: str,
        params: QueryParams | None,
        headers: Mapping[str, str] | None,
        source: str,
    ) -> Any:
        try:
            response = await self._client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError(
                f"{source}: request timed out ({type(exc).__name__})"
            ) from exc
        except httpx.TransportError as exc:
            raise UpstreamConnectionError(
                f"{source}: connection failed ({type(exc).__name__})"
            ) from exc

        status = response.status_code
        if status >= 400:
            raise self._http_error(source, response)

        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamInvalidResponseError(
                f"{source}: response body is not valid JSON"
            ) from exc

    @staticmethod
    def _http_error(source: str, response: httpx.Response) -> UpstreamHTTPError:
        status = response.status_code
        rate_limited = status == 403 and response.headers.get("x-ratelimit-remaining") == "0"
        retryable = status in RETRYABLE_STATUS_CODES
        message = f"{source}: upstream returned HTTP {status}"
        if rate_limited:
            message += " (rate limit exceeded; configure a token or retry later)"
        return UpstreamHTTPError(
            message,
            status_code=status,
            retryable=retryable,
            retry_after=parse_retry_after(response.headers.get("retry-after")),
        )
