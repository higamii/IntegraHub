"""Open-Meteo integration: current weather for a configurable list of locations."""

import datetime as dt
from collections.abc import Sequence

from pydantic import BaseModel

from integrahub.http_client import ResilientHTTPClient
from integrahub.integrations.base import BaseIntegration, FetchResult, NormalizedRecord
from integrahub.utils import Location, slugify

CURRENT_FIELDS = "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"


class OpenMeteoCurrent(BaseModel):
    time: dt.datetime
    temperature_2m: float
    wind_speed_10m: float
    relative_humidity_2m: float | None = None
    weather_code: int | None = None


class OpenMeteoResponse(BaseModel):
    latitude: float
    longitude: float
    current: OpenMeteoCurrent


def describe_weather_code(code: int | None) -> str | None:
    """Translate a WMO weather interpretation code into a short description."""
    if code is None:
        return None
    if code == 0:
        return "Clear sky"
    if code in (1, 2, 3):
        return "Partly cloudy"
    if code in (45, 48):
        return "Fog"
    if 51 <= code <= 57:
        return "Drizzle"
    if 61 <= code <= 67:
        return "Rain"
    if 71 <= code <= 77:
        return "Snow"
    if 80 <= code <= 82:
        return "Rain showers"
    if code in (85, 86):
        return "Snow showers"
    if 95 <= code <= 99:
        return "Thunderstorm"
    return "Unknown"


class WeatherIntegration(BaseIntegration):
    name = "open_meteo"
    display_name = "Open-Meteo Weather"
    description = "Current weather conditions for configured locations (no API key required)."

    def __init__(
        self,
        client: ResilientHTTPClient,
        *,
        base_url: str,
        locations: Sequence[Location],
    ) -> None:
        super().__init__(client, base_url)
        self._locations = list(locations)

    async def fetch(self) -> FetchResult:
        records: list[NormalizedRecord] = []
        attempts = 0
        for location in self._locations:
            result = await self._client.get_json(
                f"{self.base_url}/forecast",
                params={
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "current": CURRENT_FIELDS,
                },
                source=self.name,
            )
            attempts += result.attempts
            payload = self._validate(OpenMeteoResponse, result.data)
            records.append(self.normalize(location, payload))
        return FetchResult(records=records, attempts=attempts)

    @staticmethod
    def normalize(location: Location, payload: OpenMeteoResponse) -> NormalizedRecord:
        current = payload.current
        # Open-Meteo returns GMT timestamps without an offset unless a timezone is requested.
        observed_at = current.time
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=dt.UTC)
        return NormalizedRecord(
            external_id=slugify(location.name),
            record_type="weather_observation",
            data={
                "location": location.name,
                "latitude": payload.latitude,
                "longitude": payload.longitude,
                "temperature_c": current.temperature_2m,
                "relative_humidity_pct": current.relative_humidity_2m,
                "wind_speed_kmh": current.wind_speed_10m,
                "condition": describe_weather_code(current.weather_code),
                "observed_at": observed_at.isoformat(),
            },
        )
