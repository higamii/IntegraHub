"""Optional background scheduler that periodically synchronizes all integrations."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class SyncScheduler:
    """Runs ``job`` immediately and then every ``interval_seconds``.

    Failures of a run are logged and never stop the loop.
    """

    def __init__(self, interval_seconds: float, job: Callable[[], Awaitable[object]]) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be > 0")
        self._interval = interval_seconds
        self._job = job
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._loop(), name="integrahub-sync-scheduler")
        logger.info("scheduler started", extra={"interval_seconds": self._interval})

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("scheduler stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._job()
            except Exception:
                logger.exception("scheduled synchronization failed")
            await asyncio.sleep(self._interval)
