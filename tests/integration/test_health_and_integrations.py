import httpx

from integrahub import __version__

API = "/api/v1"


async def test_liveness(client: httpx.AsyncClient):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_readiness_checks_the_database(client: httpx.AsyncClient):
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


async def test_request_id_is_generated_or_echoed(client: httpx.AsyncClient):
    generated = await client.get("/health")
    echoed = await client.get("/health", headers={"X-Request-ID": "trace-abc.123"})
    rejected = await client.get("/health", headers={"X-Request-ID": "not a valid id!"})

    assert len(generated.headers["x-request-id"]) == 32
    assert echoed.headers["x-request-id"] == "trace-abc.123"
    assert rejected.headers["x-request-id"] != "not a valid id!"
    assert len(rejected.headers["x-request-id"]) == 32


async def test_swagger_and_openapi_are_served(client: httpx.AsyncClient):
    docs = await client.get("/docs")
    schema = await client.get("/openapi.json")

    assert docs.status_code == 200
    assert "swagger" in docs.text.lower()
    paths = schema.json()["paths"]
    assert f"{API}/integrations/{{name}}/sync" in paths
    assert f"{API}/monitoring/status" in paths
    assert schema.json()["info"]["title"] == "IntegraHub"


async def test_integrations_are_registered_on_startup(client: httpx.AsyncClient):
    response = await client.get(f"{API}/integrations")

    body = response.json()
    assert response.status_code == 200
    assert [item["name"] for item in body["items"]] == ["frankfurter", "github", "open_meteo"]
    assert {item["status"] for item in body["items"]} == {"unknown"}
    assert all(item["enabled"] for item in body["items"])
    assert (body["total"], body["page"], body["page_size"], body["pages"]) == (3, 1, 20, 1)


async def test_integrations_are_paginated(client: httpx.AsyncClient):
    first = (await client.get(f"{API}/integrations", params={"page_size": 2})).json()
    second = (await client.get(f"{API}/integrations", params={"page_size": 2, "page": 2})).json()
    beyond = (await client.get(f"{API}/integrations", params={"page_size": 2, "page": 9})).json()

    assert [i["name"] for i in first["items"]] == ["frankfurter", "github"]
    assert first["pages"] == 2
    assert [i["name"] for i in second["items"]] == ["open_meteo"]
    assert beyond["items"] == []
    assert beyond["total"] == 3


async def test_pagination_parameters_are_validated(client: httpx.AsyncClient):
    for params in ({"page": 0}, {"page_size": 0}, {"page_size": 101}, {"page": "x"}):
        response = await client.get(f"{API}/integrations", params=params)
        assert response.status_code == 422, params


async def test_get_integration_and_not_found(client: httpx.AsyncClient):
    found = await client.get(f"{API}/integrations/github")
    missing = await client.get(f"{API}/integrations/nope")

    assert found.status_code == 200
    assert found.json()["display_name"] == "GitHub Repositories"
    assert missing.status_code == 404
    assert missing.json() == {
        "detail": "Integration 'nope' does not exist",
        "code": "integration_not_found",
    }


async def test_disable_and_filter_integrations(client: httpx.AsyncClient):
    patched = await client.patch(f"{API}/integrations/github", json={"enabled": False})
    disabled = await client.get(f"{API}/integrations", params={"enabled": "false"})
    enabled = await client.get(f"{API}/integrations", params={"enabled": "true"})
    unknown = await client.get(f"{API}/integrations", params={"status": "unknown"})
    healthy = await client.get(f"{API}/integrations", params={"status": "healthy"})
    invalid = await client.get(f"{API}/integrations", params={"status": "bogus"})

    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert [i["name"] for i in disabled.json()["items"]] == ["github"]
    assert enabled.json()["total"] == 2
    assert unknown.json()["total"] == 3
    assert healthy.json()["total"] == 0
    assert invalid.status_code == 422


async def test_patch_validates_body(client: httpx.AsyncClient):
    response = await client.patch(f"{API}/integrations/github", json={"enabled": "maybe"})

    assert response.status_code == 422
