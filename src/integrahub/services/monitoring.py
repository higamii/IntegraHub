"""Integration health report."""

from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from integrahub.enums import IntegrationStatus, SyncStatus
from integrahub.models import Integration, SyncRun
from integrahub.schemas import IntegrationHealth, MonitoringReport, schema_from_orm
from integrahub.status import overall_status
from integrahub.utils import utcnow


async def build_status_report(session: AsyncSession, *, window_hours: int = 24) -> MonitoringReport:
    """Summarize the health of every integration over a recent time window."""
    now = utcnow()
    cutoff = now - timedelta(hours=window_hours)

    integrations = (await session.scalars(select(Integration).order_by(Integration.name))).all()

    stats_result = await session.execute(
        select(
            SyncRun.integration_id,
            func.count().label("total"),
            func.sum(case((SyncRun.status == SyncStatus.SUCCESS.value, 1), else_=0)).label(
                "succeeded"
            ),
            func.avg(SyncRun.duration_ms).label("avg_duration_ms"),
        )
        .where(SyncRun.started_at >= cutoff, SyncRun.status != SyncStatus.RUNNING.value)
        .group_by(SyncRun.integration_id)
    )
    stats = {row.integration_id: row for row in stats_result.all()}

    items: list[IntegrationHealth] = []
    for integration in integrations:
        row = stats.get(integration.id)
        total = int(row.total) if row is not None else 0
        succeeded = int(row.succeeded or 0) if row is not None else 0
        avg_ms = (
            float(row.avg_duration_ms)
            if row is not None and row.avg_duration_ms is not None
            else None
        )
        items.append(
            schema_from_orm(
                IntegrationHealth,
                integration,
                runs_in_window=total,
                success_rate=round(succeeded / total, 4) if total else None,
                avg_duration_ms=round(avg_ms, 1) if avg_ms is not None else None,
            )
        )

    enabled_statuses = [IntegrationStatus(i.status) for i in integrations if i.enabled]
    totals = {"integrations": len(integrations)}
    for status in IntegrationStatus:
        totals[status.value] = sum(1 for i in integrations if i.status == status.value)

    return MonitoringReport(
        overall_status=overall_status(enabled_statuses),
        checked_at=now,
        window_hours=window_hours,
        totals=totals,
        integrations=items,
    )
