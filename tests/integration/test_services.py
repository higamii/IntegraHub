import httpx
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from integrahub.config import Settings
from integrahub.db import create_session_factory
from integrahub.enums import SyncStatus
from integrahub.http_client import ResilientHTTPClient
from integrahub.integrations.base import NormalizedRecord
from integrahub.integrations.registry import build_integrations
from integrahub.models import Integration, SyncedRecord, SyncRun
from integrahub.retry import RetryPolicy
from integrahub.services.integrations import ensure_registered
from integrahub.services.sync import mark_interrupted_runs, upsert_records
from integrahub.utils import utcnow
from tests.fakes import FakeUpstream


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


async def make_integration(session: AsyncSession, name: str = "demo") -> Integration:
    row = Integration(
        name=name,
        display_name="Demo",
        description="Demo integration",
        base_url="https://example.test",
        enabled=True,
        status="unknown",
        consecutive_failures=0,
    )
    session.add(row)
    await session.commit()
    return row


async def test_ensure_registered_is_idempotent(
    session_factory, settings: Settings, upstream: FakeUpstream
):
    client = ResilientHTTPClient(
        timeout=1.0,
        connect_timeout=1.0,
        retry_policy=RetryPolicy(max_attempts=1),
        transport=httpx.MockTransport(upstream.handler),
    )
    try:
        integrations = build_integrations(settings, client)
        async with session_factory() as session:
            await ensure_registered(session, integrations)
            await ensure_registered(session, integrations)
            total = await session.scalar(select(func.count()).select_from(Integration))
    finally:
        await client.aclose()

    assert total == 3


async def test_upsert_creates_updates_and_skips_unchanged(session_factory):
    async with session_factory() as session:
        row = await make_integration(session)
        original = [
            NormalizedRecord(external_id="a", record_type="t", data={"v": 1}),
            NormalizedRecord(external_id="b", record_type="t", data={"v": 2}),
        ]

        first = await upsert_records(session, row.id, original)
        await session.commit()

        changed = [
            NormalizedRecord(external_id="a", record_type="t", data={"v": 1}),
            NormalizedRecord(external_id="b", record_type="t", data={"v": 99}),
            NormalizedRecord(external_id="c", record_type="t", data={"v": 3}),
        ]
        second = await upsert_records(session, row.id, changed)
        await session.commit()

        stored = {
            r.external_id: r.data for r in (await session.scalars(select(SyncedRecord))).all()
        }

    assert (first.created, first.updated, first.unchanged) == (2, 0, 0)
    assert (second.created, second.updated, second.unchanged) == (1, 1, 1)
    assert stored == {"a": {"v": 1}, "b": {"v": 99}, "c": {"v": 3}}


async def test_upsert_deduplicates_repeated_external_ids(session_factory):
    async with session_factory() as session:
        row = await make_integration(session)
        records = [
            NormalizedRecord(external_id="a", record_type="t", data={"v": 1}),
            NormalizedRecord(external_id="a", record_type="t", data={"v": 2}),
        ]

        counts = await upsert_records(session, row.id, records)
        await session.commit()
        total = await session.scalar(select(func.count()).select_from(SyncedRecord))

    assert counts.created == 1
    assert total == 1


async def test_interrupted_runs_are_closed_on_startup(session_factory):
    async with session_factory() as session:
        row = await make_integration(session)
        session.add_all(
            [
                SyncRun(integration_id=row.id, status="running", started_at=utcnow()),
                SyncRun(
                    integration_id=row.id,
                    status="success",
                    started_at=utcnow(),
                    finished_at=utcnow(),
                ),
            ]
        )
        await session.commit()

        closed = await mark_interrupted_runs(session)

    async with session_factory() as session:
        runs = (await session.scalars(select(SyncRun).order_by(SyncRun.id))).all()

    assert closed == 1
    assert [run.status for run in runs] == [SyncStatus.FAILED, SyncStatus.SUCCESS]
    assert runs[0].error_type == "Interrupted"
    assert runs[0].finished_at is not None


async def test_datetimes_round_trip_as_timezone_aware_utc(session_factory):
    async with session_factory() as session:
        row = await make_integration(session)
        row.last_sync_at = utcnow()
        await session.commit()

    async with session_factory() as session:
        stored = await session.scalar(select(Integration).where(Integration.id == row.id))

    assert stored.last_sync_at.tzinfo is not None
    assert stored.last_sync_at.utcoffset().total_seconds() == 0
