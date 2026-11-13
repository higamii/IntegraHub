import asyncio

import pytest

from integrahub.scheduler import SyncScheduler


async def test_scheduler_runs_job_repeatedly_and_stops():
    calls = 0
    reached = asyncio.Event()

    async def job() -> None:
        nonlocal calls
        calls += 1
        if calls >= 3:
            reached.set()

    scheduler = SyncScheduler(0.01, job)
    scheduler.start()
    assert scheduler.running

    await asyncio.wait_for(reached.wait(), timeout=2)
    await scheduler.stop()

    assert not scheduler.running


async def test_scheduler_survives_job_failures():
    calls = 0
    recovered = asyncio.Event()

    async def job() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("first run fails")
        recovered.set()

    scheduler = SyncScheduler(0.01, job)
    scheduler.start()
    try:
        await asyncio.wait_for(recovered.wait(), timeout=2)
    finally:
        await scheduler.stop()

    assert calls >= 2


def test_scheduler_rejects_non_positive_interval():
    async def job() -> None:
        return None

    with pytest.raises(ValueError):
        SyncScheduler(0, job)
