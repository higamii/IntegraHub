"""Read-only queries for sync history and stored records."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from integrahub.enums import SyncStatus
from integrahub.exceptions import RecordNotFoundError, SyncRunNotFoundError
from integrahub.models import Integration, SyncedRecord, SyncRun
from integrahub.pagination import Pagination


async def list_sync_runs(
    session: AsyncSession,
    pagination: Pagination,
    *,
    integration: str | None = None,
    status: SyncStatus | None = None,
) -> tuple[list[tuple[SyncRun, str]], int]:
    """Paginated sync history, newest first. Returns ``(run, integration_name)`` pairs."""
    conditions = []
    if integration is not None:
        conditions.append(Integration.name == integration)
    if status is not None:
        conditions.append(SyncRun.status == status.value)

    total = await session.scalar(
        select(func.count())
        .select_from(SyncRun)
        .join(Integration, Integration.id == SyncRun.integration_id)
        .where(*conditions)
    )
    result = await session.execute(
        select(SyncRun, Integration.name)
        .join(Integration, Integration.id == SyncRun.integration_id)
        .where(*conditions)
        .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return [(run, name) for run, name in result.all()], int(total or 0)


async def get_sync_run(session: AsyncSession, run_id: int) -> tuple[SyncRun, str]:
    result = await session.execute(
        select(SyncRun, Integration.name)
        .join(Integration, Integration.id == SyncRun.integration_id)
        .where(SyncRun.id == run_id)
    )
    row = result.first()
    if row is None:
        raise SyncRunNotFoundError(run_id)
    return row[0], row[1]


async def list_records(
    session: AsyncSession,
    pagination: Pagination,
    *,
    integration: str | None = None,
    record_type: str | None = None,
) -> tuple[list[tuple[SyncedRecord, str]], int]:
    """Paginated stored records, most recently changed first."""
    conditions = []
    if integration is not None:
        conditions.append(Integration.name == integration)
    if record_type is not None:
        conditions.append(SyncedRecord.record_type == record_type)

    total = await session.scalar(
        select(func.count())
        .select_from(SyncedRecord)
        .join(Integration, Integration.id == SyncedRecord.integration_id)
        .where(*conditions)
    )
    result = await session.execute(
        select(SyncedRecord, Integration.name)
        .join(Integration, Integration.id == SyncedRecord.integration_id)
        .where(*conditions)
        .order_by(SyncedRecord.updated_at.desc(), SyncedRecord.id.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return [(record, name) for record, name in result.all()], int(total or 0)


async def get_record(session: AsyncSession, record_id: int) -> tuple[SyncedRecord, str]:
    result = await session.execute(
        select(SyncedRecord, Integration.name)
        .join(Integration, Integration.id == SyncedRecord.integration_id)
        .where(SyncedRecord.id == record_id)
    )
    row = result.first()
    if row is None:
        raise RecordNotFoundError(record_id)
    return row[0], row[1]
