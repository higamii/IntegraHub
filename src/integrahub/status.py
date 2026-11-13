"""Pure rules that turn synchronization outcomes into integration health."""

from collections.abc import Iterable

from integrahub.enums import IntegrationStatus

#: Consecutive failures after which an integration is considered down.
DOWN_THRESHOLD = 3


def status_after_failure(consecutive_failures: int) -> IntegrationStatus:
    """Status after a failed sync: degraded at first, down once failures pile up."""
    if consecutive_failures >= DOWN_THRESHOLD:
        return IntegrationStatus.DOWN
    return IntegrationStatus.DEGRADED


def overall_status(statuses: Iterable[IntegrationStatus]) -> IntegrationStatus:
    """Aggregate the status of several integrations.

    * Integrations that never synced (``unknown``) are ignored; if all are unknown the
      result is ``unknown``.
    * ``down`` only if every known integration is down.
    * ``degraded`` if at least one known integration is degraded or down.
    * ``healthy`` otherwise.
    """
    known = [s for s in statuses if s != IntegrationStatus.UNKNOWN]
    if not known:
        return IntegrationStatus.UNKNOWN
    if all(s == IntegrationStatus.DOWN for s in known):
        return IntegrationStatus.DOWN
    if any(s in (IntegrationStatus.DEGRADED, IntegrationStatus.DOWN) for s in known):
        return IntegrationStatus.DEGRADED
    return IntegrationStatus.HEALTHY
