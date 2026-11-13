import pytest
from pydantic import ValidationError

from integrahub.config import Settings
from integrahub.utils import Location


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_defaults_are_usable():
    settings = make_settings()

    assert settings.api_key is None
    assert settings.retry_max_attempts == 4
    assert settings.exchange_symbol_list == ["BRL", "EUR", "GBP", "JPY"]
    assert settings.github_repository_list[0] == "fastapi/fastapi"
    assert settings.weather_location_list[0] == Location("Sao Paulo", -23.55, -46.63)


def test_blank_secrets_become_none():
    settings = make_settings(api_key="   ", github_token="")

    assert settings.api_key is None
    assert settings.github_token is None


def test_secrets_are_masked_in_repr():
    settings = make_settings(api_key="super-secret", github_token="ghp_secret")

    assert "super-secret" not in repr(settings)
    assert "ghp_secret" not in repr(settings)
    assert settings.api_key.get_secret_value() == "super-secret"


def test_environment_variables_override_defaults(monkeypatch):
    monkeypatch.setenv("RETRY_MAX_ATTEMPTS", "7")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("EXCHANGE_BASE", "eur")

    settings = make_settings()

    assert settings.retry_max_attempts == 7
    assert settings.log_level == "DEBUG"
    assert settings.exchange_base == "EUR"


@pytest.mark.parametrize(
    "overrides",
    [
        {"weather_locations": "Nowhere:100:0"},
        {"weather_locations": "missing-coordinates"},
        {"github_repositories": "not-a-repo"},
        {"exchange_symbols": "BRL,EU"},
        {"retry_max_attempts": 0},
        {"http_timeout_seconds": 0},
        {"environment": "staging"},
    ],
)
def test_invalid_configuration_fails_fast(overrides):
    with pytest.raises(ValidationError):
        make_settings(**overrides)
