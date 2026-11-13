"""FastAPI dependencies."""

import secrets
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from integrahub.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Pagination
from integrahub.services.sync import SyncService

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Required for write endpoints when the server has API_KEY configured.",
)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide a database session scoped to the request."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_sync_service(request: Request) -> SyncService:
    return request.app.state.sync_service


def get_pagination(
    page: Annotated[int, Query(ge=1, description="Page number (1-based)")] = 1,
    page_size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Items per page")
    ] = DEFAULT_PAGE_SIZE,
) -> Pagination:
    return Pagination(page=page, page_size=page_size)


async def require_api_key(
    request: Request,
    provided: Annotated[str | None, Security(api_key_header)],
) -> None:
    """Protect write endpoints. A no-op when no API key is configured."""
    configured = request.app.state.settings.api_key
    if configured is None:
        return
    expected = configured.get_secret_value().encode("utf-8")
    if provided is None or not secrets.compare_digest(provided.encode("utf-8"), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SyncServiceDep = Annotated[SyncService, Depends(get_sync_service)]
PaginationDep = Annotated[Pagination, Depends(get_pagination)]
