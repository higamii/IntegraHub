"""Synchronization: fetch from an integration, persist, record history, update health."""

import asyncio
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from integrahub.enums import IntegrationStatus, SyncStatus, SyncTrigger
from integrahub.exceptions import (
    IntegrationDisabledError,
    IntegrationNotFoundError,
    SyncInProgressError,
)
from integrahub.integrations.base import BaseIntegration, NormalizedRecord
from integrahub.models import Integration, SyncedRecord, SyncRun
from integrahub.schemas import SyncAllOut, SyncRunOut, schema_from_orm
from integrahub.services.integrations import get_integration_by_name
from integrahub.status import status_after_failure
from integrahub.utils import content_hash, utcnow

logger = logging.getLogger(__name__)

MAX_ERROR_MESSAGE_LENGTH = 1000


@dataclass(frozen=True)
class UpsertCounts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0


async def upsert_records(
    session: AsyncSession,
    integration_id: int,
    records: Sequence[NormalizedRecord],
) -> UpsertCounts:
    """Insert new records, update changed ones (by content hash) and touch the rest."""
    unique = {record.external_id: record for record in records}
    existing: dict[str, SyncedRecord] = {}
    if unique:
        rows = await session.scalars(
            select(SyncedRecord).where(
                SyncedRecord.integration_id == integration_id,
                SyncedRecord.external_id.in_(list(unique)),
            )
        )
        existing = {row.external_id: row for row in rows.all()}

    now = utcnow()
    created = updated = unchanged = 0
    for external_id, record in unique.items():
        digest = content_hash(record.data)
        row = existing.get(external_id)
        if row is None:
            session.add(
                SyncedRecord(
                    integration_id=integration_id,
                    external_id=external_id,
                    record_type=record.record_type,
                    data=record.data,
                    content_hash=digest,
                    created_at=now,
                    updated_at=now,
                    last_synced_at=now,
                )
            )
            created += 1
        elif row.content_hash != digest:
            row.record_type = record.record_type
            row.data = record.data
            row.content_hash = digest
            row.updated_at = now
            row.last_synced_at = now
            updated += 1
        else:
            row.last_synced_at = now
            unchanged += 1
    return UpsertCounts(created=created, updated=updated, unchanged=unchanged)


async def mark_interrupted_runs(session: AsyncSession) -> int:
    """Close runs left in ``running`` state by a previous crash or restart.

    Safe because the application runs a single instance (see README, "Limitations").
    """
    result = await session.execute(
        update(SyncRun)
        .where(SyncRun.status == SyncStatus.RUNNING.value)
        .values(
            status=SyncStatus.FAILED.value,
            finished_at=utcnow(),
            error_type="Interrupted",
            error_message="Synchronization was interrupted by an application restart",
        )
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


class SyncService:
    """Coordinates synchronizations. Holds one lock per integration (single-process)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        integrations: Mapping[str, BaseIntegration],
    ) -> None:
        self._session_factory = session_factory
        self._integrations = dict(integrations)
        self._locks = {name: asyncio.Lock() for name in self._integrations}

    async def sync_one(
        self, name: str, *, trigger: SyncTrigger = SyncTrigger.MANUAL
    ) -> SyncRunOut:
        """Synchronize one integration and return the resulting history entry.

        Raises:
            IntegrationNotFoundError: unknown integration.
            IntegrationDisabledError: integration is disabled.
            SyncInProgressError: another sync of the same integration is running.
        """
        integration = self._integrations.get(name)
        if integration is None:
            raise IntegrationNotFoundError(name)
        lock = self._locks[name]
        if lock.locked():
            raise SyncInProgressError(name)
        async with lock:
            return await self._execute(integration, trigger)

    async def sync_all(self, *, trigger: SyncTrigger = SyncTrigger.MANUAL) -> SyncAllOut:
        """Synchronize every enabled integration, one after another."""
        runs: list[SyncRunOut] = []
        skipped: list[str] = []
        for name in self._integrations:
            try:
                runs.append(await self.sync_one(name, trigger=trigger))
            except (IntegrationDisabledError, SyncInProgressError):
                skipped.append(name)
        return SyncAllOut(runs=runs, skipped=skipped)

    async def _execute(self, integration: BaseIntegration, trigger: SyncTrigger) -> SyncRunOut:
        name = integration.name
        async with self._session_factory() as session:
            row = await get_integration_by_name(session, name)
            if not row.enabled:
                raise IntegrationDisabledError(name)
            integration_id = row.id

            run = SyncRun(
                integration_id=integration_id,
                status=SyncStatus.RUNNING.value,
                trigger=trigger.value,
                started_at=utcnow(),
            )
            session.add(run)
            await session.commit()
            run_id = run.id
            logger.info(
                "sync started",
                extra={"integration": name, "run_id": run_id, "trigger": trigger.value},
            )

            timer = time.perf_counter()
            try:
                result = await integration.fetch()
                counts = await upsert_records(session, integration_id, result.records)
                duration_ms = int((time.perf_counter() - timer) * 1000)
                finished_at = utcnow()

                run.status = SyncStatus.SUCCESS.value
                run.finished_at = finished_at
                run.duration_ms = duration_ms
                run.attempts = result.attempts
                run.records_fetched = len(result.records)
                run.records_created = counts.created
                run.records_updated = counts.updated
                run.records_unchanged = counts.unchanged

                row.status = IntegrationStatus.HEALTHY.value
                row.consecutive_failures = 0
                row.last_sync_at = finished_at
                row.last_success_at = finished_at
                row.last_error = None
                row.updated_at = finished_at
                await session.commit()
                logger.info(
                    "sync succeeded",
                    extra={
                        "integration": name,
                        "run_id": run_id,
                        "duration_ms": duration_ms,
                        "attempts": result.attempts,
                        "records_fetched": len(result.records),
                        "records_created": counts.created,
                        "records_updated": counts.updated,
                        "records_unchanged": counts.unchanged,
                    },
                )
            except Exception as exc:
                await session.rollback()
                duration_ms = int((time.perf_counter() - timer) * 1000)
                run = await self._record_failure(
                    session,
                    run_id=run_id,
                    integration_id=integration_id,
                    exc=exc,
                    duration_ms=duration_ms,
                )
            return schema_from_orm(SyncRunOut, run, integration=name)

    @staticmethod
    async def _record_failure(
        session: AsyncSession,
        *,
        run_id: int,
        integration_id: int,
        exc: Exception,
        duration_ms: int,
    ) -> SyncRun:
        """Persist a failed run and degrade the integration's status."""
        message = str(exc)[:MAX_ERROR_MESSAGE_LENGTH]
        attempts = getattr(exc, "attempts", 0) or 0
        log_extra = {
            "run_id": run_id,
            "duration_ms": duration_ms,
            "attempts": attempts,
            "error_type": type(exc).__name__,
            "error": message,
        }

        run = await session.get(SyncRun, run_id)
        row = await session.get(Integration, integration_id)
        if run is None or row is None:
            raise RuntimeError("Sync bookkeeping rows disappeared during a failed sync") from exc

        finished_at = utcnow()
        run.status = SyncStatus.FAILED.value
        run.finished_at = finished_at
        run.duration_ms = duration_ms
        run.attempts = attempts
        run.error_type = type(exc).__name__
        run.error_message = message

        row.consecutive_failures += 1
        row.status = status_after_failure(row.consecutive_failures).value
        row.last_sync_at = finished_at
        row.last_error = message
        row.updated_at = finished_at
        await session.commit()

        log_extra["integration"] = row.name
        log_extra["integration_status"] = row.status
        if hasattr(exc, "retryable"):
            logger.warning("sync failed", extra=log_extra)
        else:
            logger.error("sync failed unexpectedly", extra=log_extra, exc_info=exc)
        return run
