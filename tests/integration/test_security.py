import httpx

API = "/api/v1"
VALID = {"X-API-Key": "test-secret"}


async def test_write_endpoints_require_the_api_key(secured_client: httpx.AsyncClient):
    responses = [
        await secured_client.patch(f"{API}/integrations/github", json={"enabled": False}),
        await secured_client.post(f"{API}/integrations/github/sync"),
        await secured_client.post(f"{API}/sync"),
    ]

    for response in responses:
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "ApiKey"
        assert response.json()["detail"] == "Missing or invalid API key"


async def test_wrong_api_key_is_rejected(secured_client: httpx.AsyncClient):
    response = await secured_client.post(
        f"{API}/integrations/github/sync", headers={"X-API-Key": "wrong"}
    )

    assert response.status_code == 401


async def test_valid_api_key_is_accepted(secured_client: httpx.AsyncClient):
    patched = await secured_client.patch(
        f"{API}/integrations/github", json={"enabled": True}, headers=VALID
    )
    synced = await secured_client.post(f"{API}/integrations/frankfurter/sync", headers=VALID)

    assert patched.status_code == 200
    assert synced.status_code == 201


async def test_read_endpoints_and_probes_stay_public(secured_client: httpx.AsyncClient):
    for path in (
        "/health",
        "/health/ready",
        f"{API}/integrations",
        f"{API}/sync-runs",
        f"{API}/records",
        f"{API}/monitoring/status",
    ):
        response = await secured_client.get(path)
        assert response.status_code == 200, path


async def test_api_is_open_when_no_key_is_configured(client: httpx.AsyncClient):
    response = await client.patch(f"{API}/integrations/github", json={"enabled": True})

    assert response.status_code == 200
