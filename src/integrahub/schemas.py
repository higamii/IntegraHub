"""Pydantic schemas used by the REST API (request and response bodies)."""

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from integrahub.enums import IntegrationStatus, SyncStatus, SyncTrigger

T = TypeVar("T")
SchemaT = TypeVar("SchemaT", bound=BaseModel)


def schema_from_orm(schema: type[SchemaT], obj: object, **extra: Any) -> SchemaT:
    """Build ``schema`` from the attributes of an ORM object plus extra values.

    Used where a response combines a row with a joined value (e.g. the integration name),
    avoiding ORM relationships and their lazy-loading pitfalls in async code.
    """
    data = {
        field: getattr(obj, field)
        for field in schema.model_fields
        if field not in extra and hasattr(obj, field)
    }
    return schema(**data, **extra)


class Page(BaseModel, Generic[T]):
    """Envelope for paginated list responses."""

    items: list[T]
    total: int = Field(description="Total number of items across all pages")
    page: int = Field(description="Current page (1-based)")
    page_size: int = Field(description="Maximum number of items per page")
    pages: int = Field(description="Total number of pages")


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class ReadinessOut(BaseModel):
    status: Literal["ok", "unavailable"]
    database: Literal["up", "down"]


class IntegrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    display_name: str
    description: str
    base_url: str
    enabled: bool
    status: IntegrationStatus
    consecutive_failures: int
    last_sync_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None


class IntegrationUpdate(BaseModel):
    enabled: bool


class SyncRunOut(BaseModel):
    id: int
    integration: str
    status: SyncStatus
    trigger: SyncTrigger
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    attempts: int = Field(description="HTTP attempts made against the upstream API(s)")
    records_fetched: int
    records_created: int
    records_updated: int
    records_unchanged: int
    error_type: str | None
    error_message: str | None


class SyncAllOut(BaseModel):
    runs: list[SyncRunOut]
    skipped: list[str] = Field(
        description="Integrations not synchronized (disabled or already syncing)"
    )


class RecordOut(BaseModel):
    id: int
    integration: str
    record_type: str
    external_id: str
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    last_synced_at: datetime


class IntegrationHealth(BaseModel):
    name: str
    display_name: str
    enabled: bool
    status: IntegrationStatus
    consecutive_failures: int
    last_sync_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    runs_in_window: int
    success_rate: float | None = Field(
        description="Fraction (0-1) of finished runs in the window that succeeded"
    )
    avg_duration_ms: float | None


class MonitoringReport(BaseModel):
    overall_status: IntegrationStatus
    checked_at: datetime
    window_hours: int
    totals: dict[str, int]
    integrations: list[IntegrationHealth]
