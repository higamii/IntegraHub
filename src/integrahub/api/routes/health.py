"""Liveness and readiness probes."""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from integrahub import __version__
from integrahub.api.deps import SessionDep
from integrahub.schemas import HealthOut, ReadinessOut

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut, summary="Liveness probe")
async def health() -> HealthOut:
    """Returns 200 while the process is running. Does not touch the database."""
    return HealthOut(status="ok", version=__version__)


@router.get(
    "/health/ready",
    response_model=ReadinessOut,
    summary="Readiness probe",
    responses={503: {"model": ReadinessOut, "description": "Database unavailable"}},
)
async def readiness(session: SessionDep, response: Response) -> ReadinessOut:
    """Returns 200 when the database answers queries, 503 otherwise."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness check failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessOut(status="unavailable", database="down")
    return ReadinessOut(status="ok", database="up")
