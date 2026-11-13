"""Retry with exponential backoff and jitter (stdlib only)."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff configuration.

    The delay before retry ``n`` (1-based) is ``base_delay * 2 ** (n - 1)``, capped at
    ``max_delay`` and then randomized by ``+/- jitter`` (a fraction) to avoid
    synchronized retries ("thundering herd").
    """

    max_attempts: int = 4
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.2
    max_retry_after: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay < 0 or self.max_delay < 0 or self.max_retry_after < 0:
            raise ValueError("delays must be >= 0")
        if not 0 <= self.jitter <= 1:
            raise ValueError("jitter must be between 0 and 1")

    def backoff(self, attempt: int) -> float:
        """Deterministic delay (no jitter) after the given failed attempt (1-based)."""
        return min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))

    def delay_for(self, attempt: int, rng: Callable[[], float] = random.random) -> float:
        """Delay after the given failed attempt, including jitter."""
        base = self.backoff(attempt)
        if base == 0 or self.jitter == 0:
            return base
        spread = base * self.jitter
        delay = base + (rng() * 2 - 1) * spread
        return min(self.max_delay, max(0.0, delay))


async def retry_async(
    operation: Callable[[int], Awaitable[T]],
    *,
    policy: RetryPolicy,
    should_retry: Callable[[Exception], bool],
    get_retry_after: Callable[[Exception], float | None] | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: Callable[[], float] = random.random,
) -> T:
    """Run ``operation(attempt)`` until it succeeds, retrying retryable failures.

    Args:
        operation: coroutine function receiving the 1-based attempt number.
        policy: backoff configuration.
        should_retry: decides whether an exception is worth retrying.
        get_retry_after: optional server hint (seconds) overriding the computed backoff.
        on_retry: callback ``(failed_attempt, exception, delay)`` before sleeping.
        sleep: injectable for tests.
        rng: injectable random source in ``[0, 1)`` for tests.

    Raises:
        Exception: the last exception when attempts are exhausted or it is not retryable.
    """
    attempt = 1
    while True:
        try:
            return await operation(attempt)
        except Exception as exc:
            if attempt >= policy.max_attempts or not should_retry(exc):
                raise
            delay = policy.delay_for(attempt, rng)
            if get_retry_after is not None:
                hinted = get_retry_after(exc)
                if hinted is not None:
                    delay = min(max(hinted, 0.0), policy.max_retry_after)
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            await sleep(delay)
            attempt += 1
