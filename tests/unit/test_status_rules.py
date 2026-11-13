from integrahub.enums import IntegrationStatus as S
from integrahub.status import overall_status, status_after_failure


def test_status_after_failure_escalates():
    assert status_after_failure(1) == S.DEGRADED
    assert status_after_failure(2) == S.DEGRADED
    assert status_after_failure(3) == S.DOWN
    assert status_after_failure(10) == S.DOWN


def test_overall_status_rules():
    assert overall_status([]) == S.UNKNOWN
    assert overall_status([S.UNKNOWN, S.UNKNOWN]) == S.UNKNOWN
    assert overall_status([S.HEALTHY, S.UNKNOWN]) == S.HEALTHY
    assert overall_status([S.HEALTHY, S.HEALTHY]) == S.HEALTHY
    assert overall_status([S.HEALTHY, S.DEGRADED]) == S.DEGRADED
    assert overall_status([S.HEALTHY, S.DOWN]) == S.DEGRADED
    assert overall_status([S.DOWN, S.DOWN, S.UNKNOWN]) == S.DOWN
