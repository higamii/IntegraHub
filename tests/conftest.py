"""Shared fixtures.

By default the suite runs against in-memory SQLite (fast, no setup). Set
``TEST_DATABASE_URL`` (e.g. ``postgresql+asyncpg://...``) to run the same tests on
PostgreSQL, which is what the CI pipeline does.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

import integrahub.models  # noqa: F401  (registers the models on Base.metadata)
from integrahub.config import Settings
from integrahub.db import Base
from integrahub.main import create_app
from tests.fakes import FakeUpstream

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture
def settings() -> Settings:
    """Hermetic settings: nothing is read from the environment or a .env file."""
    return Settings(
        _env_file=None,
        environment="test",
        log_level="WARNING",
        log_json=False,
        database_url=TEST_DATABASE_URL,
        api_key=None,
        github_token=None,
        retry_max_attempts=3,
        retry_base_delay_seconds=0.0,
        retry_max_delay_seconds=0.0,
        sync_interval_seconds=0,
        open_meteo_base_url="https://api.open-meteo.com/v1",
        frankfurter_base_url="https://api.frankfurter.dev/v1",
        github_base_url="https://api.github.com",
        weather_locations="Sao Paulo:-23.55:-46.63,London:51.51:-0.13,Tokyo:35.68:139.69",
        exchange_base="USD",
        exchange_symbols="BRL,EUR,GBP,JPY",
        github_repositories="fastapi/fastapi,encode/httpx,sqlalchemy/sqlalchemy",
    )


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    if TEST_DATABASE_URL.startswith("sqlite"):
        test_engine = create_async_engine(
            TEST_DATABASE_URL,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    else:
        test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)

    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield test_engine
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@asynccontextmanager
async def running_client(
    settings: Settings, engine: AsyncEngine, upstream: FakeUpstream
) -> AsyncIterator[httpx.AsyncClient]:
    """Start the app (including its lifespan) and yield an HTTP client bound to it."""
    app = create_app(settings, engine=engine, http_transport=httpx.MockTransport(upstream.handler))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest_asyncio.fixture
async def client(
    settings: Settings, engine: AsyncEngine, upstream: FakeUpstream
) -> AsyncIterator[httpx.AsyncClient]:
    async with running_client(settings, engine, upstream) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def secured_client(
    settings: Settings, engine: AsyncEngine, upstream: FakeUpstream
) -> AsyncIterator[httpx.AsyncClient]:
    secured = settings.model_copy(update={"api_key": SecretStr("test-secret")})
    async with running_client(secured, engine, upstream) as test_client:
        yield test_client
