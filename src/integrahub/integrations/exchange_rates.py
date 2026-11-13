"""Frankfurter integration: daily foreign-exchange reference rates (ECB data)."""

import datetime as dt
from collections.abc import Sequence

from pydantic import BaseModel, Field, field_validator

from integrahub.http_client import ResilientHTTPClient
from integrahub.integrations.base import BaseIntegration, FetchResult, NormalizedRecord


class FrankfurterResponse(BaseModel):
    base: str
    rate_date: dt.date = Field(alias="date")
    rates: dict[str, float]

    @field_validator("rates")
    @classmethod
    def _rates_must_be_positive(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("no rates returned")
        if any(rate <= 0 for rate in value.values()):
            raise ValueError("rates must be positive")
        return value


class ExchangeRateIntegration(BaseIntegration):
    name = "frankfurter"
    display_name = "Frankfurter Exchange Rates"
    description = "Daily foreign-exchange reference rates for a base currency (no API key)."

    def __init__(
        self,
        client: ResilientHTTPClient,
        *,
        base_url: str,
        base_currency: str,
        symbols: Sequence[str],
    ) -> None:
        super().__init__(client, base_url)
        self._base_currency = base_currency
        self._symbols = list(symbols)

    async def fetch(self) -> FetchResult:
        result = await self._client.get_json(
            f"{self.base_url}/latest",
            params={"base": self._base_currency, "symbols": ",".join(self._symbols)},
            source=self.name,
        )
        payload = self._validate(FrankfurterResponse, result.data)
        return FetchResult(records=self.normalize(payload), attempts=result.attempts)

    @staticmethod
    def normalize(payload: FrankfurterResponse) -> list[NormalizedRecord]:
        return [
            NormalizedRecord(
                external_id=f"{payload.base}-{quote}",
                record_type="exchange_rate",
                data={
                    "base": payload.base,
                    "quote": quote,
                    "rate": rate,
                    "rate_date": payload.rate_date.isoformat(),
                },
            )
            for quote, rate in sorted(payload.rates.items())
        ]
