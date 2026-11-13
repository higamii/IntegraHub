"""Shared enumerations (stored as plain strings in the database)."""

from enum import StrEnum


class IntegrationStatus(StrEnum):
    """Health of an integration, derived from its recent synchronizations."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


class SyncStatus(StrEnum):
    """Lifecycle of a single synchronization run."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class SyncTrigger(StrEnum):
    """What started a synchronization run."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"
