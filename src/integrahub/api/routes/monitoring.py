"""Integration monitoring endpoint."""

from typing import Annotated

from fastapi import APIRouter, Query

from integrahub.api.deps import SessionDep
from integrahub.schemas import MonitoringReport
from integrahub.services.monitoring import build_status_report

router = APIRouter(tags=["monitoring"])


@router.get(
    "/monitoring/status",
    response_model=MonitoringReport,
    summary="Health of all integrations",
    description=(
        "Current status of each integration plus success rate and average duration of the "
        "synchronizations that started within the requested window."
    ),
)
async def monitoring_status(
    session: SessionDep,
    window_hours: Annotated[
        int, Query(ge=1, le=168, description="Look-back window for run statistics")
    ] = 24,
) -> MonitoringReport:
    return await build_status_report(session, window_hours=window_hours)
