"""Endpoints exposing the normalized data stored by synchronizations."""

from typing import Annotated

from fastapi import APIRouter, Query

from integrahub.api.deps import PaginationDep, SessionDep
from integrahub.pagination import page_meta
from integrahub.schemas import ErrorResponse, Page, RecordOut, schema_from_orm
from integrahub.services import history

router = APIRouter(tags=["records"])


@router.get(
    "/records",
    response_model=Page[RecordOut],
    summary="List stored records",
    description="Most recently changed records first.",
)
async def list_records(
    session: SessionDep,
    pagination: PaginationDep,
    integration: Annotated[
        str | None, Query(description="Filter by integration name, e.g. `open_meteo`")
    ] = None,
    record_type: Annotated[
        str | None,
        Query(description="Filter by type: weather_observation, exchange_rate, github_repository"),
    ] = None,
) -> Page[RecordOut]:
    rows, total = await history.list_records(
        session, pagination, integration=integration, record_type=record_type
    )
    return Page[RecordOut](
        items=[schema_from_orm(RecordOut, record, integration=name) for record, name in rows],
        **page_meta(total, pagination),
    )


@router.get(
    "/records/{record_id}",
    response_model=RecordOut,
    summary="Get one stored record",
    responses={404: {"model": ErrorResponse, "description": "Record not found"}},
)
async def get_record(record_id: int, session: SessionDep) -> RecordOut:
    record, name = await history.get_record(session, record_id)
    return schema_from_orm(RecordOut, record, integration=name)
