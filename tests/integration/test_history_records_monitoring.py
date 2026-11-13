import httpx

from tests.fakes import FakeUpstream

API = "/api/v1"


async def test_sync_history_is_listed_newest_first_with_filters(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    await client.post(f"{API}/integrations/frankfurter/sync")
    upstream.fail_always(FakeUpstream.GITHUB, 500)
    await client.post(f"{API}/integrations/github/sync")
    await client.post(f"{API}/integrations/frankfurter/sync")

    history = (await client.get(f"{API}/sync-runs")).json()
    only_failed = (await client.get(f"{API}/sync-runs", params={"status": "failed"})).json()
    only_fx = (await client.get(f"{API}/sync-runs", params={"integration": "frankfurter"})).json()
    nothing = (await client.get(f"{API}/sync-runs", params={"integration": "open_meteo"})).json()

    assert history["total"] == 3
    ids = [run["id"] for run in history["items"]]
    assert ids == sorted(ids, reverse=True)
    assert [run["integration"] for run in history["items"]] == [
        "frankfurter",
        "github",
        "frankfurter",
    ]
    assert only_failed["total"] == 1
    assert only_failed["items"][0]["integration"] == "github"
    assert only_fx["total"] == 2
    assert nothing["items"] == []


async def test_sync_history_is_paginated(client: httpx.AsyncClient):
    for _ in range(3):
        await client.post(f"{API}/integrations/frankfurter/sync")

    page_one = (await client.get(f"{API}/sync-runs", params={"page_size": 2})).json()
    page_two = (await client.get(f"{API}/sync-runs", params={"page_size": 2, "page": 2})).json()

    assert (page_one["total"], page_one["pages"]) == (3, 2)
    assert len(page_one["items"]) == 2
    assert len(page_two["items"]) == 1
    assert page_two["items"][0]["id"] < page_one["items"][-1]["id"]


async def test_get_sync_run_by_id(client: httpx.AsyncClient):
    created = (await client.post(f"{API}/integrations/github/sync")).json()

    found = await client.get(f"{API}/sync-runs/{created['id']}")
    missing = await client.get(f"{API}/sync-runs/9999")
    invalid_status = await client.get(f"{API}/sync-runs", params={"status": "bogus"})

    assert found.status_code == 200
    assert found.json() == created
    assert missing.status_code == 404
    assert missing.json()["code"] == "sync_run_not_found"
    assert invalid_status.status_code == 422


async def test_records_can_be_filtered_paginated_and_fetched(client: httpx.AsyncClient):
    await client.post(f"{API}/sync")

    everything = (await client.get(f"{API}/records")).json()
    weather = (await client.get(f"{API}/records", params={"integration": "open_meteo"})).json()
    rates = (await client.get(f"{API}/records", params={"record_type": "exchange_rate"})).json()
    last_page = (await client.get(f"{API}/records", params={"page_size": 4, "page": 3})).json()

    assert everything["total"] == 10
    assert weather["total"] == 3
    assert {r["record_type"] for r in weather["items"]} == {"weather_observation"}
    assert rates["total"] == 4
    assert (last_page["pages"], len(last_page["items"])) == (3, 2)

    sao_paulo = next(r for r in weather["items"] if r["external_id"] == "sao-paulo")
    detail = await client.get(f"{API}/records/{sao_paulo['id']}")
    assert detail.status_code == 200
    assert detail.json() == sao_paulo
    assert sao_paulo["integration"] == "open_meteo"
    assert sao_paulo["data"]["condition"] == "Partly cloudy"


async def test_record_not_found(client: httpx.AsyncClient):
    response = await client.get(f"{API}/records/9999")

    assert response.status_code == 404
    assert response.json()["code"] == "record_not_found"


async def test_monitoring_reports_per_integration_health(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    await client.post(f"{API}/integrations/frankfurter/sync")
    upstream.fail_always(FakeUpstream.GITHUB, 500)
    for _ in range(3):
        await client.post(f"{API}/integrations/github/sync")

    response = await client.get(f"{API}/monitoring/status")

    report = response.json()
    assert response.status_code == 200
    assert report["overall_status"] == "degraded"
    assert report["window_hours"] == 24
    assert report["totals"] == {
        "integrations": 3,
        "unknown": 1,
        "healthy": 1,
        "degraded": 0,
        "down": 1,
    }
    by_name = {item["name"]: item for item in report["integrations"]}
    assert [item["name"] for item in report["integrations"]] == [
        "frankfurter",
        "github",
        "open_meteo",
    ]
    assert by_name["frankfurter"]["status"] == "healthy"
    assert by_name["frankfurter"]["runs_in_window"] == 1
    assert by_name["frankfurter"]["success_rate"] == 1.0
    assert by_name["github"]["status"] == "down"
    assert by_name["github"]["consecutive_failures"] == 3
    assert by_name["github"]["runs_in_window"] == 3
    assert by_name["github"]["success_rate"] == 0.0
    assert by_name["open_meteo"]["status"] == "unknown"
    assert by_name["open_meteo"]["success_rate"] is None
    assert by_name["open_meteo"]["avg_duration_ms"] is None


async def test_monitoring_ignores_disabled_integrations_for_overall_status(
    client: httpx.AsyncClient, upstream: FakeUpstream
):
    await client.post(f"{API}/integrations/frankfurter/sync")
    upstream.fail_always(FakeUpstream.GITHUB, 500)
    await client.post(f"{API}/integrations/github/sync")
    await client.patch(f"{API}/integrations/github", json={"enabled": False})

    report = (await client.get(f"{API}/monitoring/status")).json()

    assert report["overall_status"] == "healthy"


async def test_monitoring_with_no_activity_is_unknown(client: httpx.AsyncClient):
    report = (await client.get(f"{API}/monitoring/status")).json()

    assert report["overall_status"] == "unknown"


async def test_monitoring_window_is_validated(client: httpx.AsyncClient):
    for window in (0, 169):
        response = await client.get(f"{API}/monitoring/status", params={"window_hours": window})
        assert response.status_code == 422
