"""Application settings, loaded from environment variables (and an optional ``.env``)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from integrahub.utils import (
    Location,
    parse_currencies,
    parse_locations,
    parse_repositories,
)


class Settings(BaseSettings):
    """All runtime configuration. Secrets use ``SecretStr`` so they never leak into logs."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_name: str = "IntegraHub"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True

    # Database
    database_url: str = "postgresql+asyncpg://integrahub:integrahub@localhost:5432/integrahub"

    # Security
    api_key: SecretStr | None = None
    github_token: SecretStr | None = None

    # HTTP client / resilience
    http_timeout_seconds: float = Field(default=10.0, gt=0)
    http_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    retry_max_attempts: int = Field(default=4, ge=1, le=10)
    retry_base_delay_seconds: float = Field(default=0.5, ge=0)
    retry_max_delay_seconds: float = Field(default=8.0, ge=0)

    # Synchronization
    sync_interval_seconds: int = Field(default=0, ge=0)

    # Integrations
    open_meteo_base_url: str = "https://api.open-meteo.com/v1"
    frankfurter_base_url: str = "https://api.frankfurter.dev/v1"
    github_base_url: str = "https://api.github.com"
    weather_locations: str = "Sao Paulo:-23.55:-46.63,London:51.51:-0.13,Tokyo:35.68:139.69"
    exchange_base: str = "USD"
    exchange_symbols: str = "BRL,EUR,GBP,JPY"
    github_repositories: str = "fastapi/fastapi,encode/httpx,sqlalchemy/sqlalchemy"

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("api_key", "github_token", mode="before")
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("weather_locations")
    @classmethod
    def _validate_locations(cls, value: str) -> str:
        parse_locations(value)
        return value

    @field_validator("github_repositories")
    @classmethod
    def _validate_repositories(cls, value: str) -> str:
        parse_repositories(value)
        return value

    @field_validator("exchange_symbols")
    @classmethod
    def _validate_symbols(cls, value: str) -> str:
        parse_currencies(value)
        return value

    @field_validator("exchange_base")
    @classmethod
    def _validate_base(cls, value: str) -> str:
        if len(parse_currencies(value)) != 1:
            raise ValueError("exchange_base must be a single currency code")
        return value.strip().upper()

    @property
    def weather_location_list(self) -> list[Location]:
        return parse_locations(self.weather_locations)

    @property
    def exchange_symbol_list(self) -> list[str]:
        return parse_currencies(self.exchange_symbols)

    @property
    def github_repository_list(self) -> list[str]:
        return parse_repositories(self.github_repositories)


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance for application code."""
    return Settings()
