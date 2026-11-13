# IntegraHub

[![CI](https://github.com/higamii/integrahub/actions/workflows/ci.yml/badge.svg)](https://github.com/higamii/integrahub/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)
![License](https://img.shields.io/badge/license-MIT-green)

**IntegraHub** is a backend service that integrates with external REST APIs, validates and
normalizes their JSON, stores the result in PostgreSQL, keeps a full history of every
synchronization and exposes the health of each integration through its own documented REST API.

It is built to demonstrate production-minded backend practices: resilient HTTP calls
(timeouts, retries with exponential backoff), structured logging, schema migrations,
layered architecture, automated tests and a CI pipeline.

## Table of contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Usage examples](#usage-examples)
- [API reference](#api-reference)
- [Configuration](#configuration)
- [Credentials](#credentials)
- [Resilience](#resilience)
- [Observability](#observability)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Design decisions](#design-decisions)
- [Limitations](#limitations)

## Features

| Area | What is implemented |
| --- | --- |
| **Integrations** | Three external APIs, none requiring credentials: [Open-Meteo](https://open-meteo.com/) (weather), [Frankfurter](https://frankfurter.dev/) (exchange rates) and the [GitHub REST API](https://docs.github.com/rest) (repository metadata; token optional). |
| **Data pipeline** | Fetch, validate with Pydantic models, normalize into a common record shape, upsert into PostgreSQL. A content hash classifies each record as *created*, *updated* or *unchanged*. |
| **Synchronization** | On-demand (`POST /sync`, `POST /integrations/{name}/sync`) and an optional background scheduler. One sync per integration at a time. |
| **Resilience** | Connect/read timeouts, retries with exponential backoff and jitter for timeouts, connection errors, `429` and `5xx`, `Retry-After` support, fail-fast on other `4xx` and on invalid payloads. |
| **History** | Every run is stored: trigger, duration, HTTP attempts, record counts, error type and message. |
| **Monitoring** | Per-integration status (`unknown`, `healthy`, `degraded`, `down`), consecutive failures, success rate and average duration over a configurable window. |
| **REST API** | Pagination and filters on every list endpoint, consistent error bodies, Swagger UI (`/docs`) and ReDoc (`/redoc`). |
| **Security basics** | Optional API key for write endpoints (constant-time comparison), secrets held as `SecretStr`, non-root container, no secrets in the repository, validated request ids. |
| **Operations** | Alembic migrations, JSON logs with request correlation ids, liveness/readiness probes, Docker, Docker Compose, GitHub Actions. |

## Architecture

```mermaid
flowchart LR
    client([API client]) -->|HTTP| api

    subgraph IntegraHub
        api["FastAPI routes<br/>(validation, auth, pagination)"]
        svc["Services<br/>sync - history - monitoring"]
        adapters["Integration adapters<br/>weather - exchange rates - GitHub"]
        http["Resilient HTTP client<br/>timeouts - retries - backoff"]
        sched["Optional scheduler"]
        api --> svc
        sched --> svc
        svc --> adapters
        adapters --> http
    end

    svc -->|SQLAlchemy async| db[(PostgreSQL)]
    http -->|HTTPS| ext1([Open-Meteo])
    http -->|HTTPS| ext2([Frankfurter])
    http -->|HTTPS| ext3([GitHub API])
```

**Layers**

- `api/` – HTTP concerns only: routing, request validation, authentication, response models.
- `services/` – business logic: the sync workflow, history queries, health aggregation.
- `integrations/` – one adapter per external API. Each fetches, validates (Pydantic) and
  normalizes into `NormalizedRecord`. Adding an integration means adding one class and
  registering it.
- `http_client.py` / `retry.py` – all resilience logic in one place, independent from any provider.

### What happens during a sync

```mermaid
sequenceDiagram
    participant C as Client
    participant S as SyncService
    participant I as Integration adapter
    participant H as Resilient HTTP client
    participant E as External API
    participant D as PostgreSQL

    C->>S: POST /integrations/{name}/sync
    S->>D: insert sync_run (status=running)
    S->>I: fetch()
    loop up to RETRY_MAX_ATTEMPTS
        I->>H: get_json(url)
        H->>E: GET
        E-->>H: 200 / 5xx / timeout
        Note over H: transient failure -> wait base * 2^(n-1), jittered, then retry
    end
    H-->>I: parsed JSON (or UpstreamError)
    I-->>S: normalized records
    S->>D: upsert records, finish sync_run, update integration status
    S-->>C: 201 + sync run
```

### Data model

```mermaid
erDiagram
    integrations ||--o{ sync_runs : "has history"
    integrations ||--o{ synced_records : "owns"

    integrations {
        int id PK
        string name UK
        string status
        bool enabled
        int consecutive_failures
        datetime last_sync_at
        datetime last_success_at
        text last_error
    }
    sync_runs {
        int id PK
        int integration_id FK
        string status
        string trigger
        datetime started_at
        datetime finished_at
        int duration_ms
        int attempts
        int records_created
        int records_updated
        int records_unchanged
        string error_type
        text error_message
    }
    synced_records {
        int id PK
        int integration_id FK
        string external_id
        string record_type
        jsonb data
        string content_hash
        datetime updated_at
        datetime last_synced_at
    }
```

`(integration_id, external_id)` is unique, so re-syncing updates records in place.

### Integration health

| Event | Resulting status |
| --- | --- |
| Never synchronized | `unknown` |
| Successful sync | `healthy`, failure counter reset |
| 1-2 consecutive failures | `degraded` |
| 3 or more consecutive failures | `down` |

The overall status of `GET /api/v1/monitoring/status` ignores disabled and never-synced
integrations: `down` if every known integration is down, `degraded` if at least one is
degraded or down, `healthy` otherwise, `unknown` if nothing has been synced yet.

## Quick start

### Option A - Docker Compose (recommended)

Requires Docker with the Compose plugin.

```bash
cp .env.example .env          # optional: only needed to change defaults
docker compose up --build -d
```

Compose starts PostgreSQL, waits until it is healthy, applies the migrations and starts the API.

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- Health: <http://localhost:8000/health>

Stop everything with `docker compose down` (add `-v` to also delete the database volume).

### Option B - Local development

Requires Python 3.11+ and a PostgreSQL instance. The easiest way to get one is to start only
the database from Compose:

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env
docker compose up -d db                                # PostgreSQL on localhost:5432

alembic upgrade head
uvicorn integrahub.main:create_app --factory --reload --app-dir src
```

`make install`, `make migrate`, `make run`, `make test` and `make lint` wrap the same commands.

## Usage examples

Trigger a synchronization and inspect the result (the `X-API-Key` header is only needed when
`API_KEY` is configured):

```bash
curl -X POST http://localhost:8000/api/v1/integrations/frankfurter/sync \
     -H "X-API-Key: $API_KEY"
```

Example response (abridged, illustrative values):

```json
{
  "id": 1,
  "integration": "frankfurter",
  "status": "success",
  "trigger": "manual",
  "duration_ms": 312,
  "attempts": 1,
  "records_fetched": 4,
  "records_created": 4,
  "records_updated": 0,
  "records_unchanged": 0,
  "error_type": null,
  "error_message": null
}
```

Synchronize every enabled integration:

```bash
curl -X POST http://localhost:8000/api/v1/sync
```

Browse the normalized data, with filters and pagination:

```bash
curl "http://localhost:8000/api/v1/records?record_type=exchange_rate&page=1&page_size=10"
curl "http://localhost:8000/api/v1/records?integration=open_meteo"
```

Review the synchronization history:

```bash
curl "http://localhost:8000/api/v1/sync-runs?status=failed&integration=github"
```

Check the health of all integrations over the last 24 hours:

```bash
curl "http://localhost:8000/api/v1/monitoring/status?window_hours=24"
```

Disable an integration (it is then skipped by `POST /sync`):

```bash
curl -X PATCH http://localhost:8000/api/v1/integrations/github \
     -H "Content-Type: application/json" -d '{"enabled": false}'
```

Paginated responses share one envelope:

```json
{ "items": [], "total": 42, "page": 1, "page_size": 20, "pages": 3 }
```

Errors share one shape: `{"detail": "...", "code": "integration_not_found"}`
(validation errors use FastAPI's standard `422` body).

## API reference

Base path: `/api/v1`. Interactive documentation: `/docs`.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/health` | - | Liveness probe |
| GET | `/health/ready` | - | Readiness probe (checks the database, `503` if unavailable) |
| GET | `/integrations` | - | List integrations. Filters: `status`, `enabled` |
| GET | `/integrations/{name}` | - | Integration details and health |
| PATCH | `/integrations/{name}` | key* | Enable or disable an integration |
| POST | `/integrations/{name}/sync` | key* | Synchronize one integration (`409` if disabled or already running) |
| POST | `/sync` | key* | Synchronize all enabled integrations |
| GET | `/sync-runs` | - | Sync history, newest first. Filters: `integration`, `status` |
| GET | `/sync-runs/{id}` | - | One sync run |
| GET | `/records` | - | Stored records. Filters: `integration`, `record_type` |
| GET | `/records/{id}` | - | One stored record |
| GET | `/monitoring/status` | - | Health report. Parameter: `window_hours` (1-168) |

\* Required only when the server runs with `API_KEY` set. `/health*` is mounted at the root,
not under `/api/v1`. All list endpoints accept `page` (>= 1) and `page_size` (1-100, default 20).

Built-in integrations:

| Name | Source | Records produced |
| --- | --- | --- |
| `open_meteo` | Open-Meteo `/forecast?current=...` | `weather_observation`, one per configured location |
| `frankfurter` | Frankfurter `/latest` | `exchange_rate`, one per target currency |
| `github` | GitHub `/repos/{owner}/{repo}` | `github_repository`, one per configured repository |

## Configuration

All settings are environment variables (a `.env` file is also read). See
[`.env.example`](.env.example) for the complete, commented list.

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://integrahub:integrahub@localhost:5432/integrahub` | Async SQLAlchemy URL |
| `API_KEY` | *(empty)* | Protects write endpoints when set |
| `GITHUB_TOKEN` | *(empty)* | Optional GitHub token (see below) |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `true` | Log verbosity / JSON or human-readable output |
| `HTTP_TIMEOUT_SECONDS` | `10` | Read timeout for upstream calls |
| `HTTP_CONNECT_TIMEOUT_SECONDS` | `5` | Connect timeout for upstream calls |
| `RETRY_MAX_ATTEMPTS` | `4` | Total attempts per upstream request |
| `RETRY_BASE_DELAY_SECONDS` / `RETRY_MAX_DELAY_SECONDS` | `0.5` / `8` | Backoff base and cap |
| `SYNC_INTERVAL_SECONDS` | `0` | Background sync period; `0` disables the scheduler |
| `WEATHER_LOCATIONS` | 3 cities | `Name:lat:lon,Name:lat:lon` |
| `EXCHANGE_BASE` / `EXCHANGE_SYMBOLS` | `USD` / `BRL,EUR,GBP,JPY` | Base currency and targets |
| `GITHUB_REPOSITORIES` | 3 popular repos | `owner/repo,owner/repo` |
| `*_BASE_URL` | public endpoints | Override upstream base URLs |

Invalid configuration (for example a malformed location) makes the application fail at startup
with a clear message instead of failing later at runtime.

## Credentials

None of the integrations *requires* credentials, so the project works out of the box.

- **`GITHUB_TOKEN` (optional).** Without a token GitHub allows 60 requests per hour per IP,
  which is plenty for the defaults but can be exhausted by frequent scheduled syncs. To raise
  the limit to 5,000/hour: GitHub → *Settings → Developer settings → Personal access tokens →
  Fine-grained tokens*, create a token with **no extra permissions** (public data only) and set
  `GITHUB_TOKEN` in `.env`. When the limit is hit, the sync fails with an explicit "rate limit
  exceeded" error recorded in the history and the integration becomes `degraded`.
- **`API_KEY` (recommended whenever the API is reachable by others).** Generate one with
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`, set it in `.env` and send it
  as `X-API-Key`. In Swagger UI use the **Authorize** button. When `ENVIRONMENT=production`
  and no key is set, a warning is logged at startup.
- **Database password.** `docker-compose.yml` defaults to `integrahub` for local convenience.
  Set `POSTGRES_PASSWORD` to a strong, URL-safe value for anything beyond local use.

## Resilience

| Situation | Behavior |
| --- | --- |
| Timeout, connection error | Retried with backoff |
| HTTP `408`, `425`, `429`, `500`, `502`, `503`, `504` | Retried with backoff; numeric `Retry-After` is honoured (capped at 30 s) |
| Other `4xx` (including `404` and GitHub rate-limit `403`) | Not retried; recorded as a failed run |
| `2xx` with invalid JSON or an unexpected shape | Not retried; recorded as `UpstreamInvalidResponseError` |

The delay before retry *n* is `RETRY_BASE_DELAY_SECONDS * 2^(n-1)`, capped at
`RETRY_MAX_DELAY_SECONDS`, with ±20 % jitter. With the defaults: ~0.5 s, ~1 s, ~2 s.

A failed sync never loses previously stored data and is always recorded. Runs left in the
`running` state by a crash are closed as failed (`Interrupted`) at the next startup.

## Observability

Logs are JSON, one object per line, and carry a correlation id (`X-Request-ID` is accepted
when valid, otherwise generated, and always returned in the response):

```json
{"timestamp": "2026-11-10T12:00:01.412+00:00", "level": "WARNING", "logger": "integrahub.http_client", "message": "upstream request failed, retrying", "request_id": "5f0c...", "integration": "github", "attempt": 1, "max_attempts": 4, "retry_in_seconds": 0.52, "error_type": "UpstreamHTTPError", "error": "github: upstream returned HTTP 503"}
```

Set `LOG_JSON=false` for human-readable output during development. Secrets are never logged.

## Testing

```bash
pip install -r requirements-dev.txt
pytest --cov
```

- **Unit tests** (`tests/unit`): retry/backoff maths and behavior, HTTP client error mapping,
  adapters and normalization, configuration parsing, logging, scheduler, pure status rules.
- **Integration tests** (`tests/integration`): the real FastAPI app with a real database,
  exercising endpoints end to end - sync flow, retries, failure and recovery, history,
  records, pagination, filters, monitoring, authentication and OpenAPI.
- **No network access is needed.** External APIs are replaced by an in-memory fake served
  through `httpx.MockTransport` (`tests/fakes.py`), which can inject timeouts, error statuses
  and malformed payloads.
- **Database.** By default tests run on in-memory SQLite. Set `TEST_DATABASE_URL` to run the
  same suite on PostgreSQL, which is what CI does:

  ```bash
  docker compose up -d db
  TEST_DATABASE_URL=postgresql+asyncpg://integrahub:integrahub@localhost:5432/integrahub pytest
  ```

  Warning: the test fixtures **drop and recreate all IntegraHub tables** in that database;
  use a dedicated one.

### CI/CD

`.github/workflows/ci.yml` runs on every push to `main` and on pull requests:

1. **Lint** - `ruff check`.
2. **Tests** - against a PostgreSQL 16 service container: first `alembic upgrade head` and
   `alembic downgrade base` (migrations must apply and roll back), then `pytest` with coverage.
3. **Docker** - builds the image, starts the Compose stack, waits for health checks and
   smoke-tests `/health`, `/health/ready` and `/api/v1/integrations`.

Dependabot is configured for pip, GitHub Actions and Docker.

## Project structure

```text
.
├── alembic/                    # migrations (async env + initial schema)
├── src/integrahub/
│   ├── main.py                 # app factory, lifespan, middleware, error handlers
│   ├── config.py               # typed settings (pydantic-settings)
│   ├── db.py / models.py       # async engine, UTC datetime type, ORM models
│   ├── schemas.py              # API schemas and pagination envelope
│   ├── http_client.py          # resilient HTTP client
│   ├── retry.py                # backoff policy and retry loop (stdlib only)
│   ├── logging_config.py       # JSON logging and request-id context
│   ├── scheduler.py            # optional periodic sync
│   ├── status.py               # pure health-status rules
│   ├── api/                    # dependencies and routers
│   ├── services/               # sync, history, monitoring, integration queries
│   └── integrations/           # base class, three adapters, registry
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fakes.py                # fake upstream APIs
│   └── conftest.py
├── Dockerfile
├── docker-compose.yml
└── .github/workflows/ci.yml
```

## Design decisions

- **Async end to end** (FastAPI, SQLAlchemy 2.0 async with asyncpg, HTTPX), so slow upstream
  APIs never block the event loop.
- **Adapters hide each provider.** The sync workflow only knows `BaseIntegration.fetch()`
  and `NormalizedRecord`; provider quirks stay inside the adapter.
- **Validate at the boundary.** Upstream JSON is parsed with Pydantic models; anything
  unexpected becomes a recorded failure instead of corrupt data.
- **Change detection by content hash**, so a sync reports what actually changed and
  `updated_at` is meaningful.
- **No ORM relationships.** Queries join explicitly, which avoids lazy-loading surprises in
  async code.
- **Retry logic is its own tiny module** with an injectable clock and random source, which
  makes the backoff deterministic to test.
- **Portable schema.** `JSONB` on PostgreSQL, plain JSON elsewhere, and a custom type that
  returns timezone-aware UTC datetimes on every backend.
- **Stateless request handling.** The sync service uses its own database session, so the
  HTTP request and the scheduler share exactly the same code path.

## Limitations

These are deliberate scope limits, not hidden features:

- **Single instance.** The per-integration lock and the cleanup of interrupted runs are
  in-process. Running several replicas would need a distributed lock (for example a
  PostgreSQL advisory lock) and one scheduler. The Docker image runs a single worker.
- **Synchronous sync endpoints.** `POST .../sync` waits for completion. A job queue would
  be the next step for long-running integrations.
- **Sequential fetching** inside an integration (for example the three weather locations);
  fine at this scale, easily parallelized with `asyncio.gather`.
- **Latest-value storage.** Records are upserted; the project keeps a history of *syncs*,
  not of every past value of a record.
- **Frankfurter** is consumed through its v1 API. If the provider retires it, only the
  adapter (and `FRANKFURTER_BASE_URL`) needs updating.
- **API key authentication** is intentionally simple (one shared key for write endpoints).
  There are no users, roles or rate limiting.

## License

[MIT](LICENSE)
