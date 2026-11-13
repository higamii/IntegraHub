"""Application factory."""

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from integrahub import __version__
from integrahub.api.routes import health, integrations, monitoring, records, sync_runs
from integrahub.config import Settings, get_settings
from integrahub.db import create_engine, create_session_factory
from integrahub.enums import SyncTrigger
from integrahub.exceptions import IntegraHubError
from integrahub.http_client import ResilientHTTPClient
from integrahub.integrations.registry import build_integrations
from integrahub.logging_config import configure_logging, request_id_var
from integrahub.retry import RetryPolicy
from integrahub.scheduler import SyncScheduler
from integrahub.services.integrations import ensure_registered
from integrahub.services.sync import SyncService, mark_interrupted_runs

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")

DESCRIPTION = """
Integration and monitoring platform for external APIs.

* **Integrations** - Open-Meteo (weather), Frankfurter (exchange rates), GitHub (repositories).
* **Synchronization** - fetch, validate, normalize and store data; every run is recorded.
* **Monitoring** - per-integration health, success rate and latency.

Write endpoints (`PATCH`/`POST`) require the `X-API-Key` header when the server is
configured with an `API_KEY`.
"""

TAGS_METADATA = [
    {"name": "integrations", "description": "Manage integrations and trigger synchronizations."},
    {"name": "sync history", "description": "Audit trail of every synchronization run."},
    {"name": "records", "description": "Normalized data stored by synchronizations."},
    {"name": "monitoring", "description": "Health of the integrations."},
    {"name": "health", "description": "Liveness and readiness probes."},
]


def create_app(
    settings: Settings | None = None,
    *,
    engine: AsyncEngine | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        settings: configuration (defaults to environment variables).
        engine: pre-built database engine (tests); the caller then owns its lifecycle.
        http_transport: custom httpx transport for upstream calls (tests use a mock).
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owns_engine = engine is None
        db_engine = engine if engine is not None else create_engine(settings.database_url)
        session_factory = create_session_factory(db_engine)
        http_client = ResilientHTTPClient(
            timeout=settings.http_timeout_seconds,
            connect_timeout=settings.http_connect_timeout_seconds,
            retry_policy=RetryPolicy(
                max_attempts=settings.retry_max_attempts,
                base_delay=settings.retry_base_delay_seconds,
                max_delay=settings.retry_max_delay_seconds,
            ),
            transport=http_transport,
        )
        integration_adapters = build_integrations(settings, http_client)
        sync_service = SyncService(session_factory, integration_adapters)

        async with session_factory() as session:
            await ensure_registered(session, integration_adapters)
            interrupted = await mark_interrupted_runs(session)
        if interrupted:
            logger.warning("closed interrupted sync runs", extra={"count": interrupted})

        app.state.settings = settings
        app.state.engine = db_engine
        app.state.session_factory = session_factory
        app.state.sync_service = sync_service

        scheduler: SyncScheduler | None = None
        if settings.sync_interval_seconds > 0:

            async def scheduled_sync() -> object:
                return await sync_service.sync_all(trigger=SyncTrigger.SCHEDULED)

            scheduler = SyncScheduler(settings.sync_interval_seconds, scheduled_sync)
            scheduler.start()

        if settings.environment == "production" and settings.api_key is None:
            logger.warning("API_KEY is not set: write endpoints are unauthenticated")
        logger.info(
            "application started",
            extra={
                "version": __version__,
                "environment": settings.environment,
                "integrations": sorted(integration_adapters),
            },
        )
        try:
            yield
        finally:
            if scheduler is not None:
                await scheduler.stop()
            await http_client.aclose()
            if owns_engine:
                await db_engine.dispose()
            logger.info("application stopped")

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
    )
    # Available before startup so dependencies (e.g. API-key auth) can always read it.
    app.state.settings = settings

    @app.middleware("http")
    async def request_logging(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID_PATTERN.fullmatch(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled error",
                extra={"http_method": request.method, "path": request.url.path},
            )
            request_id_var.reset(token)
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request completed",
            extra={
                "http_method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        request_id_var.reset(token)
        return response

    @app.exception_handler(IntegraHubError)
    async def handle_domain_error(request: Request, exc: IntegraHubError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc), "code": exc.code},
        )

    app.include_router(health.router)
    for module in (integrations, sync_runs, records, monitoring):
        app.include_router(module.router, prefix=API_PREFIX)
    return app
