"""Queries and commands for registered integrations."""

from collections.abc import Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from integrahub.enums import IntegrationStatus
from integrahub.exceptions import IntegrationNotFoundError
from integrahub.integrations.base import BaseIntegration
from integrahub.models import Integration
from integrahub.pagination import Pagination
from integrahub.utils import utcnow


async def ensure_registered(
    session: AsyncSession, integrations: Mapping[str, BaseIntegration]
) -> None:
    """Create missing integration rows and refresh descriptive metadata."""
    existing = {
        row.name: row
        for row in (await session.scalars(select(Integration))).all()
    }
    for name, integration in integrations.items():
        row = existing.get(name)
        if row is None:
            session.add(
                Integration(
                    name=name,
                    display_name=integration.display_name,
                    description=integration.description,
                    base_url=integration.base_url,
                    enabled=True,
                    status=IntegrationStatus.UNKNOWN.value,
                    consecutive_failures=0,
                )
            )
        else:
            row.display_name = integration.display_name
            row.description = integration.description
            row.base_url = integration.base_url
    await session.commit()


async def get_integration_by_name(session: AsyncSession, name: str) -> Integration:
    row = await session.scalar(select(Integration).where(Integration.name == name))
    if row is None:
        raise IntegrationNotFoundError(name)
    return row


async def list_integrations(
    session: AsyncSession,
    pagination: Pagination,
    *,
    status: IntegrationStatus | None = None,
    enabled: bool | None = None,
) -> tuple[list[Integration], int]:
    conditions = []
    if status is not None:
        conditions.append(Integration.status == status.value)
    if enabled is not None:
        conditions.append(Integration.enabled == enabled)

    total = await session.scalar(select(func.count()).select_from(Integration).where(*conditions))
    rows = await session.scalars(
        select(Integration)
        .where(*conditions)
        .order_by(Integration.name)
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return list(rows.all()), int(total or 0)


async def set_enabled(session: AsyncSession, name: str, enabled: bool) -> Integration:
    row = await get_integration_by_name(session, name)
    row.enabled = enabled
    row.updated_at = utcnow()
    await session.commit()
    return row
