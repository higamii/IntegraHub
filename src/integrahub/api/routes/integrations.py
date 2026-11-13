"""Integration management and synchronization endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from integrahub.api.deps import PaginationDep, SessionDep, SyncServiceDep, require_api_key
from integrahub.enums import IntegrationStatus, SyncTrigger
from integrahub.pagination import page_meta
from integrahub.schemas import (
    ErrorResponse,
    IntegrationOut,
    IntegrationUpdate,
    Page,
    SyncAllOut,
    SyncRunOut,
)
from integrahub.services import integrations as integration_service

router = APIRouter(tags=["integrations"])

NOT_FOUND = {404: {"model": ErrorResponse, "description": "Integration not found"}}
UNAUTHORIZED = {401: {"model": ErrorResponse, "description": "Missing or invalid API key"}}


@router.get("/integrations", response_model=Page[IntegrationOut], summary="List integrations")
async def list_integrations(
    session: SessionDep,
    pagination: PaginationDep,
    status_filter: Annotated[
        IntegrationStatus | None, Query(alias="status", description="Filter by health status")
    ] = None,
    enabled: Annotated[bool | None, Query(description="Filter by enabled flag")] = None,
) -> Page[IntegrationOut]:
    rows, total = await integration_service.list_integrations(
        session, pagination, status=status_filter, enabled=enabled
    )
    return Page[IntegrationOut](
        items=[IntegrationOut.model_validate(row) for row in rows],
        **page_meta(total, pagination),
    )


@router.get(
    "/integrations/{name}",
    response_model=IntegrationOut,
    summary="Get an integration",
    responses=NOT_FOUND,
)
async def get_integration(name: str, session: SessionDep) -> IntegrationOut:
    row = await integration_service.get_integration_by_name(session, name)
    return IntegrationOut.model_validate(row)


@router.patch(
    "/integrations/{name}",
    response_model=IntegrationOut,
    summary="Enable or disable an integration",
    dependencies=[Depends(require_api_key)],
    responses={**NOT_FOUND, **UNAUTHORIZED},
)
async def update_integration(
    name: str, body: IntegrationUpdate, session: SessionDep
) -> IntegrationOut:
    row = await integration_service.set_enabled(session, name, body.enabled)
    return IntegrationOut.model_validate(row)


@router.post(
    "/integrations/{name}/sync",
    response_model=SyncRunOut,
    status_code=status.HTTP_201_CREATED,
    summary="Synchronize one integration",
    description=(
        "Fetches data from the external API, stores it and records the run. The request "
        "waits for the sync to finish. A failed sync still returns 201: inspect `status` and "
        "`error_message` in the returned run."
    ),
    dependencies=[Depends(require_api_key)],
    responses={
        **NOT_FOUND,
        **UNAUTHORIZED,
        409: {"model": ErrorResponse, "description": "Integration disabled or already syncing"},
    },
)
async def sync_integration(name: str, service: SyncServiceDep) -> SyncRunOut:
    return await service.sync_one(name, trigger=SyncTrigger.MANUAL)


@router.post(
    "/sync",
    response_model=SyncAllOut,
    summary="Synchronize all enabled integrations",
    dependencies=[Depends(require_api_key)],
    responses=UNAUTHORIZED,
)
async def sync_all(service: SyncServiceDep) -> SyncAllOut:
    return await service.sync_all(trigger=SyncTrigger.MANUAL)
