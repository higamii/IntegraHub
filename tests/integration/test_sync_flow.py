import asyncio

import httpx

from tests.fakes import FakeUpstream

API = "/api/v1"


async def sync(client: httpx.AsyncClient, name: str) -> httpx.Response:
    return await client.post(f"{API}/integrations/{name}/sync")


async def test_successful_sync_stores_records_and_marks_integration_healthy(
    client: httpx.AsyncClient,
):
    response = await sync(client, "frankfurter")

    run = response.json()
    assert response.status_code == 201
    assert run["integration"] == "frankfurter"
    assert run["status"] == "success"
    assert run["trigger"] == "manual"
    assert run["attempts"] == 1
    assert (run["records_fetched"], run["records_created"]) == (4, 4)
    assert (run["records_updated"], run["records_unchanged"]) == (0, 0)
    assert run["error_type"] is None
    assert run["duration_ms"] >= 0
    assert run["finished_at"] is not None

    integration = (await client.get(f"{API}/integrations/frankfurter")).json()
    assert integration["status"] == "healthy"
    assert integration["consecutive_failures"] == 0
    assert integration["last_error"] is None
    assert integration["last_success_at"].endswith("Z")

    records = (await client.get(f"{API}/records", params={"integration": "frankfurter"})).json()
    assert records["total"] == 4
    brl = next(r for r in records["items"] if r["external_id"] == "USD-BRL")
    assert brl["record_type"] == "exchange_rate"
    assert brl["data"]["rate"] == 5.0


async def test_resync_detects_unchanged_and_updated_records(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    await sync(client, "github")
    unchanged = (await sync(client, "github")).json()

    upstream.star_bonus = 25
    updated = (await sync(client, "github")).json()

    assert (unchanged["records_created"], unchanged["records_unchanged"]) == (0, 3)
    assert (updated["records_updated"], updated["records_unchanged"]) == (3, 0)
    records = (await client.get(f"{API}/records", params={"integration": "github"})).json()
    assert records["total"] == 3
    fastapi = next(r for r in records["items"] if r["external_id"] == "fastapi/fastapi")
    assert fastapi["data"]["stars"] == 90025


async def test_sync_all_runs_every_enabled_integration(client: httpx.AsyncClient):
    await client.patch(f"{API}/integrations/open_meteo", json={"enabled": False})

    response = await client.post(f"{API}/sync")

    body = response.json()
    assert response.status_code == 200
    assert [run["integration"] for run in body["runs"]] == ["frankfurter", "github"]
    assert {run["status"] for run in body["runs"]} == {"success"}
    assert body["skipped"] == ["open_meteo"]
    assert (await client.get(f"{API}/records")).json()["total"] == 7


async def test_transient_failures_are_retried_transparently(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    upstream.fail_next(FakeUpstream.FRANKFURTER, 503, 502)

    run = (await sync(client, "frankfurter")).json()

    assert run["status"] == "success"
    assert run["attempts"] == 3
    assert upstream.calls_to(FakeUpstream.FRANKFURTER) == 3


async def test_persistent_failures_are_recorded_and_degrade_then_down(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    upstream.fail_always(FakeUpstream.GITHUB, 500)

    expected_status = ["degraded", "degraded", "down"]
    for failures, expected in enumerate(expected_status, start=1):
        response = await sync(client, "github")
        run = response.json()
        assert response.status_code == 201
        assert run["status"] == "failed"
        assert run["error_type"] == "UpstreamHTTPError"
        assert "HTTP 500" in run["error_message"]
        assert run["attempts"] == 3
        assert run["records_fetched"] == 0

        integration = (await client.get(f"{API}/integrations/github")).json()
        assert integration["status"] == expected
        assert integration["consecutive_failures"] == failures
        assert "HTTP 500" in integration["last_error"]

    # The service recovers: status returns to healthy and the failure counter resets.
    upstream.recover(FakeUpstream.GITHUB)
    recovered = (await sync(client, "github")).json()
    integration = (await client.get(f"{API}/integrations/github")).json()
    assert recovered["status"] == "success"
    assert integration["status"] == "healthy"
    assert integration["consecutive_failures"] == 0


async def test_timeouts_are_reported_after_retries(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    upstream.fail_always(FakeUpstream.OPEN_METEO, httpx.ReadTimeout)

    run = (await sync(client, "open_meteo")).json()

    assert run["status"] == "failed"
    assert run["error_type"] == "UpstreamTimeoutError"
    assert run["attempts"] == 3


async def test_non_transient_http_errors_are_not_retried(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    upstream.fail_always(FakeUpstream.GITHUB, 404)

    run = (await sync(client, "github")).json()

    assert run["status"] == "failed"
    assert run["attempts"] == 1
    assert upstream.calls_to(FakeUpstream.GITHUB) == 1


async def test_invalid_upstream_payload_fails_the_sync(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    upstream.malformed.add(FakeUpstream.FRANKFURTER)

    run = (await sync(client, "frankfurter")).json()

    assert run["status"] == "failed"
    assert run["error_type"] == "UpstreamInvalidResponseError"
    assert "unexpected response shape" in run["error_message"]
    assert (await client.get(f"{API}/records")).json()["total"] == 0


async def test_failed_sync_keeps_previously_stored_records(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    await sync(client, "frankfurter")
    upstream.fail_always(FakeUpstream.FRANKFURTER, 503)

    await sync(client, "frankfurter")

    records = (await client.get(f"{API}/records", params={"integration": "frankfurter"})).json()
    assert records["total"] == 4


async def test_sync_of_disabled_or_unknown_integration_is_rejected(client: httpx.AsyncClient):
    await client.patch(f"{API}/integrations/github", json={"enabled": False})

    disabled = await sync(client, "github")
    unknown = await sync(client, "nope")

    assert disabled.status_code == 409
    assert disabled.json()["code"] == "integration_disabled"
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "integration_not_found"


async def test_concurrent_sync_of_the_same_integration_is_rejected(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    upstream.gate = asyncio.Event()
    first = asyncio.create_task(sync(client, "frankfurter"))
    await asyncio.wait_for(upstream.entered.wait(), timeout=5)

    second = await sync(client, "frankfurter")
    upstream.gate.set()
    first_response = await first

    assert second.status_code == 409
    assert second.json()["code"] == "sync_in_progress"
    assert first_response.status_code == 201
    assert first_response.json()["status"] == "success"
