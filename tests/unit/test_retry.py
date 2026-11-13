import pytest

from integrahub.retry import RetryPolicy, retry_async


class Recorder:
    """Collects the delays passed to ``sleep`` instead of actually sleeping."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)


def test_backoff_doubles_and_is_capped():
    policy = RetryPolicy(max_attempts=6, base_delay=0.5, max_delay=4.0, jitter=0.0)
    assert [policy.backoff(n) for n in range(1, 6)] == [0.5, 1.0, 2.0, 4.0, 4.0]


def test_jitter_stays_within_bounds():
    policy = RetryPolicy(base_delay=1.0, max_delay=8.0, jitter=0.2)
    assert policy.delay_for(1, rng=lambda: 0.5) == pytest.approx(1.0)
    assert policy.delay_for(1, rng=lambda: 0.0) == pytest.approx(0.8)
    assert policy.delay_for(2, rng=lambda: 1.0) == pytest.approx(2.4)


def test_jitter_never_exceeds_max_delay():
    policy = RetryPolicy(base_delay=1.0, max_delay=8.0, jitter=0.2)
    assert policy.delay_for(4, rng=lambda: 1.0) == 8.0


@pytest.mark.parametrize(
    "kwargs",
    [{"max_attempts": 0}, {"base_delay": -1}, {"jitter": 1.5}, {"max_retry_after": -1}],
)
def test_invalid_policy_is_rejected(kwargs):
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)


async def test_succeeds_after_transient_failures():
    recorder = Recorder()
    calls: list[int] = []

    async def flaky(attempt: int) -> str:
        calls.append(attempt)
        if attempt < 3:
            raise ConnectionError("boom")
        return "ok"

    result = await retry_async(
        flaky,
        policy=RetryPolicy(max_attempts=4, base_delay=0.5, max_delay=8, jitter=0),
        should_retry=lambda exc: isinstance(exc, ConnectionError),
        sleep=recorder.sleep,
    )

    assert result == "ok"
    assert calls == [1, 2, 3]
    assert recorder.delays == [0.5, 1.0]


async def test_raises_last_error_when_attempts_are_exhausted():
    recorder = Recorder()

    async def always_fails(attempt: int) -> None:
        raise ConnectionError(f"failure {attempt}")

    with pytest.raises(ConnectionError, match="failure 3"):
        await retry_async(
            always_fails,
            policy=RetryPolicy(max_attempts=3, base_delay=0.1, jitter=0),
            should_retry=lambda exc: True,
            sleep=recorder.sleep,
        )
    assert len(recorder.delays) == 2


async def test_non_retryable_error_is_raised_immediately():
    recorder = Recorder()
    calls: list[int] = []

    async def fatal(attempt: int) -> None:
        calls.append(attempt)
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        await retry_async(
            fatal,
            policy=RetryPolicy(),
            should_retry=lambda exc: False,
            sleep=recorder.sleep,
        )
    assert calls == [1]
    assert recorder.delays == []


async def test_retry_after_hint_overrides_backoff_and_is_capped():
    recorder = Recorder()
    seen: list[tuple[int, float]] = []

    class RateLimited(Exception):
        retry_after = 7.0

    async def operation(attempt: int) -> str:
        if attempt == 1:
            raise RateLimited()
        return "done"

    await retry_async(
        operation,
        policy=RetryPolicy(base_delay=0.1, jitter=0, max_retry_after=5.0),
        should_retry=lambda exc: True,
        get_retry_after=lambda exc: getattr(exc, "retry_after", None),
        on_retry=lambda attempt, exc, delay: seen.append((attempt, delay)),
        sleep=recorder.sleep,
    )

    assert recorder.delays == [5.0]
    assert seen == [(1, 5.0)]
