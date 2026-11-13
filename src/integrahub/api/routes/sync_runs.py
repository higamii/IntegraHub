"""Synchronization history endpoints."""

from typing import Annotated

from fastapi import APIRouter, Query

from integrahub.api.deps import PaginationDep, SessionDep
from integrahub.enums import SyncStatus
from integrahub.pagination import page_meta
from integrahub.schemas import ErrorResponse, Page, SyncRunOut, schema_from_orm
from integrahub.services import history

router = APIRouter(tags=["sync history"])


@router.get(
    "/sync-runs",
    response_model=Page[SyncRunOut],
    summary="List synchronization history",
    description="Newest runs first.",
)
async def list_sync_runs(
    session: SessionDep,
    pagination: PaginationDep,
    integration: Annotated[
        str | None, Query(description="Filter by integration name, e.g. `github`")
    ] = None,
    status_filter: Annotated[
        SyncStatus | None, Query(alias="status", description="Filter by run status")
    ] = None,
) -> Page[SyncRunOut]:
    rows, total = await history.list_sync_runs(
        session, pagination, integration=integration, status=status_filter
    )
    return Page[SyncRunOut](
        items=[schema_from_orm(SyncRunOut, run, integration=name) for run, name in rows],
        **page_meta(total, pagination),
    )


@router.get(
    "/sync-runs/{run_id}",
    response_model=SyncRunOut,
    summary="Get one synchronization run",
    responses={404: {"model": ErrorResponse, "description": "Run not found"}},
)
async def get_sync_run(run_id: int, session: SessionDep) -> SyncRunOut:
    run, name = await history.get_sync_run(session, run_id)
    return schema_from_orm(SyncRunOut, run, integration=name)
