"""Builds the set of integrations from application settings."""

from integrahub.config import Settings
from integrahub.http_client import ResilientHTTPClient
from integrahub.integrations.base import BaseIntegration
from integrahub.integrations.exchange_rates import ExchangeRateIntegration
from integrahub.integrations.github import GitHubIntegration
from integrahub.integrations.weather import WeatherIntegration


def build_integrations(
    settings: Settings, client: ResilientHTTPClient
) -> dict[str, BaseIntegration]:
    """Instantiate every integration, keyed by its unique name."""
    token = settings.github_token.get_secret_value() if settings.github_token else None
    integrations: list[BaseIntegration] = [
        WeatherIntegration(
            client,
            base_url=settings.open_meteo_base_url,
            locations=settings.weather_location_list,
        ),
        ExchangeRateIntegration(
            client,
            base_url=settings.frankfurter_base_url,
            base_currency=settings.exchange_base,
            symbols=settings.exchange_symbol_list,
        ),
        GitHubIntegration(
            client,
            base_url=settings.github_base_url,
            repositories=settings.github_repository_list,
            token=token,
        ),
    ]
    return {integration.name: integration for integration in integrations}
