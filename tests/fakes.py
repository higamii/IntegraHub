"""In-memory stand-in for the external APIs, served through ``httpx.MockTransport``."""

import asyncio

import httpx

OutcomeT = int | type[httpx.HTTPError]

KNOWN_REPOS = {
    "fastapi/fastapi": (160001, "FastAPI framework", "Python", 90000, 7600, 120),
    "encode/httpx": (1, "A next generation HTTP client", "Python", 14000, 850, 150),
    "sqlalchemy/sqlalchemy": (2, "The Database Toolkit for Python", "Python", 9500, 1500, 90),
}


class FakeUpstream:
    """Routes requests by host, with scriptable failures for resilience tests."""

    OPEN_METEO = "api.open-meteo.com"
    FRANKFURTER = "api.frankfurter.dev"
    GITHUB = "api.github.com"

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.temperature = 21.5
        self.base_rate = 5.0
        self.star_bonus = 0
        self.malformed: set[str] = set()
        self._scripted: dict[str, list[OutcomeT]] = {}
        self._always: dict[str, OutcomeT] = {}
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()

    # -- failure scripting ---------------------------------------------------------
    def fail_next(self, host: str, *outcomes: OutcomeT) -> None:
        """Make the next requests to ``host`` fail with a status code or exception type."""
        self._scripted.setdefault(host, []).extend(outcomes)

    def fail_always(self, host: str, outcome: OutcomeT) -> None:
        self._always[host] = outcome

    def recover(self, host: str) -> None:
        self._always.pop(host, None)
        self._scripted.pop(host, None)
        self.malformed.discard(host)

    def calls_to(self, host: str) -> int:
        return sum(1 for request in self.requests if request.url.host == host)

    # -- transport handler ---------------------------------------------------------
    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host

        if self.gate is not None:
            self.entered.set()
            await self.gate.wait()

        outcome = self._next_outcome(host)
        if outcome is not None:
            if isinstance(outcome, int):
                return httpx.Response(outcome, json={"message": "scripted failure"})
            raise outcome("simulated network failure", request=request)

        if host in self.malformed:
            return httpx.Response(200, json={"unexpected": "shape"})
        if host == self.OPEN_METEO:
            return self._open_meteo(request)
        if host == self.FRANKFURTER:
            return self._frankfurter(request)
        if host == self.GITHUB:
            return self._github(request)
        return httpx.Response(404, json={"message": f"unknown host {host}"})

    def _next_outcome(self, host: str) -> OutcomeT | None:
        scripted = self._scripted.get(host)
        if scripted:
            return scripted.pop(0)
        return self._always.get(host)

    def _open_meteo(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        return httpx.Response(
            200,
            json={
                "latitude": float(params["latitude"]),
                "longitude": float(params["longitude"]),
                "current": {
                    "time": "2026-11-10T12:00",
                    "interval": 900,
                    "temperature_2m": self.temperature,
                    "relative_humidity_2m": 60,
                    "wind_speed_10m": 11.5,
                    "weather_code": 3,
                },
            },
        )

    def _frankfurter(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        symbols = params["symbols"].split(",")
        rates = {
            symbol: round(self.base_rate * (index + 1), 4) for index, symbol in enumerate(symbols)
        }
        return httpx.Response(
            200,
            json={"amount": 1.0, "base": params["base"], "date": "2026-11-09", "rates": rates},
        )

    def _github(self, request: httpx.Request) -> httpx.Response:
        full_name = request.url.path.removeprefix("/repos/")
        known = KNOWN_REPOS.get(full_name)
        if known is None:
            return httpx.Response(404, json={"message": "Not Found"})
        repo_id, description, language, stars, forks, issues = known
        return httpx.Response(
            200,
            json={
                "id": repo_id,
                "full_name": full_name,
                "html_url": f"https://github.com/{full_name}",
                "description": description,
                "language": language,
                "stargazers_count": stars + self.star_bonus,
                "forks_count": forks,
                "open_issues_count": issues,
                "pushed_at": "2026-11-09T18:30:00Z",
                "archived": False,
            },
        )
