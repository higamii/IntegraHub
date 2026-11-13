import httpx
import pytest

from integrahub.exceptions import UpstreamInvalidResponseError
from integrahub.http_client import ResilientHTTPClient
from integrahub.integrations.exchange_rates import ExchangeRateIntegration
from integrahub.integrations.github import GitHubIntegration
from integrahub.integrations.weather import WeatherIntegration, describe_weather_code
from integrahub.retry import RetryPolicy
from integrahub.utils import Location
from tests.fakes import FakeUpstream


@pytest.fixture
async def http_client(upstream: FakeUpstream):
    client = ResilientHTTPClient(
        timeout=1.0,
        connect_timeout=1.0,
        retry_policy=RetryPolicy(max_attempts=1, base_delay=0, max_delay=0),
        transport=httpx.MockTransport(upstream.handler),
    )
    yield client
    await client.aclose()


async def test_weather_normalization(http_client):
    integration = WeatherIntegration(
        http_client,
        base_url="https://api.open-meteo.com/v1/",
        locations=[Location("São Paulo", -23.55, -46.63), Location("Tokyo", 35.68, 139.69)],
    )

    result = await integration.fetch()

    assert result.attempts == 2
    assert [record.external_id for record in result.records] == ["sao-paulo", "tokyo"]
    first = result.records[0]
    assert first.record_type == "weather_observation"
    assert first.data["location"] == "São Paulo"
    assert first.data["temperature_c"] == 21.5
    assert first.data["wind_speed_kmh"] == 11.5
    assert first.data["condition"] == "Partly cloudy"
    assert first.data["observed_at"] == "2026-11-10T12:00:00+00:00"


async def test_exchange_rate_normalization(http_client):
    integration = ExchangeRateIntegration(
        http_client,
        base_url="https://api.frankfurter.dev/v1",
        base_currency="USD",
        symbols=["BRL", "EUR"],
    )

    result = await integration.fetch()

    assert [record.external_id for record in result.records] == ["USD-BRL", "USD-EUR"]
    brl = result.records[0]
    assert brl.record_type == "exchange_rate"
    assert brl.data == {"base": "USD", "quote": "BRL", "rate": 5.0, "rate_date": "2026-11-09"}


async def test_github_normalization_and_optional_token(http_client, upstream):
    anonymous = GitHubIntegration(
        http_client, base_url="https://api.github.com", repositories=["fastapi/fastapi"]
    )
    authenticated = GitHubIntegration(
        http_client,
        base_url="https://api.github.com",
        repositories=["encode/httpx"],
        token="ghp_example_token",
    )

    result = await anonymous.fetch()
    await authenticated.fetch()

    record = result.records[0]
    assert record.external_id == "fastapi/fastapi"
    assert record.data["stars"] == 90000
    assert record.data["pushed_at"] == "2026-11-09T18:30:00+00:00"
    assert "authorization" not in upstream.requests[0].headers
    assert upstream.requests[1].headers["authorization"] == "Bearer ghp_example_token"
    assert upstream.requests[1].headers["accept"] == "application/vnd.github+json"


@pytest.mark.parametrize(
    "host", [FakeUpstream.OPEN_METEO, FakeUpstream.FRANKFURTER, FakeUpstream.GITHUB]
)
async def test_unexpected_payload_shape_is_reported(http_client, upstream, host):
    upstream.malformed.add(host)
    integrations = {
        FakeUpstream.OPEN_METEO: WeatherIntegration(
            http_client, base_url="https://api.open-meteo.com/v1", locations=[Location("X", 0, 0)]
        ),
        FakeUpstream.FRANKFURTER: ExchangeRateIntegration(
            http_client,
            base_url="https://api.frankfurter.dev/v1",
            base_currency="USD",
            symbols=["BRL"],
        ),
        FakeUpstream.GITHUB: GitHubIntegration(
            http_client, base_url="https://api.github.com", repositories=["fastapi/fastapi"]
        ),
    }

    with pytest.raises(UpstreamInvalidResponseError, match="unexpected response shape"):
        await integrations[host].fetch()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (None, None),
        (0, "Clear sky"),
        (2, "Partly cloudy"),
        (45, "Fog"),
        (53, "Drizzle"),
        (63, "Rain"),
        (73, "Snow"),
        (81, "Rain showers"),
        (86, "Snow showers"),
        (96, "Thunderstorm"),
        (123, "Unknown"),
    ],
)
def test_describe_weather_code(code, expected):
    assert describe_weather_code(code) == expected
