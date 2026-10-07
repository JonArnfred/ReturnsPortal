# Development guide

Everything needed to work on Returns Portal itself: setup in detail, running it, the API contract
rules, tests and quality checks, and running it outside `dev.sh`. Start with the
[README](../README.md) for what the project is, and [VISION.md](VISION.md) for the accounting model
and the decisions behind it. [AGENTS.md](../AGENTS.md) holds the rules and traps that are not obvious
from the code, for coding agents and people alike.

## Stack

- Litestar API with typed OpenAPI 3.1 contracts, stable operation IDs, request IDs, safe errors,
  allowed-host and request-size enforcement
- Postgres through psycopg 3 with explicit SQL, dbmate migrations, and the PnL engine as SQL functions
- Redis and Celery (worker and beat) for broker syncs, prices, FX and rebuilds; Flower in development
- React Router frontend with server-side rendering, MUI, Highcharts, and types generated from the
  OpenAPI document
- Dependency-free liveness plus Postgres/Redis readiness probes, and an optional daily health email
- Locked Python and npm dependencies, Ruff, mypy, ESLint, TypeScript, and GitHub Actions CI

## First setup

The repository pins Python in `.python-version`, Node in `.nvmrc`, Python dependencies in
`uv.lock`, and frontend dependencies in `package-lock.json`.

```bash
uv sync --locked
cd frontend && npm ci && cd ..
cp backend/.env.example backend/.env
```

uv creates the environment in `.venv`, which `dev.sh` uses. To keep it elsewhere (for example
when the checkout lives in a synced folder such as Dropbox), export `UV_PROJECT_ENVIRONMENT` with
the path before `uv sync`; `uv run` and `dev.sh` then use that location too.

Fill in the Postgres and Redis values in `backend/.env`, generate `SECRETS_ENCRYPTION_KEY` with
`uv run python backend/scripts/generate_encryption_key.py`, and add broker credentials as described
in [BROKER_SETUP.md](BROKER_SETUP.md). `dev.sh` applies the migrations and the engine's SQL
functions on every start; to do it by hand (requires dbmate):

```bash
cd backend
DATABASE_URL="$(uv run python -c 'from app.config import settings; print(settings.database_url)')" dbmate --no-dump-schema up
uv run python scripts/apply_db_functions.py
cd ..
```

The schema lives in `backend/db/migrations/`, one dbmate migration per table as of the first public
release (`…_create_<table>.sql`, in foreign-key order). A later change goes in a new migration file;
an applied migration is never edited. The PnL engine's functions and views are not migrations; they
live in `backend/db/functions/` and are re-applied on every start. Integration tests apply every
migration in order, like dbmate.

## Run locally

```bash
./dev.sh
```

Defaults:

- API: `http://localhost:18020`
- Frontend: `http://localhost:25183`
- Flower: `http://localhost:25183/flower/` through the development-only SSR proxy; log in with
  `FLOWER_BASIC_AUTH`, or with the random password `dev.sh` prints when that is not set

Override ports with `API_PORT`, `FRONTEND_PORT`, and `FLOWER_PORT`. If configured Redis is
unavailable and `redis-server` is installed, `dev.sh` starts a private loopback instance. The dev
proxy in `frontend/server.mjs` is not hot-reloaded and the Celery worker does not pick up new
tasks; restart `dev.sh` after changing either.

Each startup also queues a background catch-up: fetch ECB FX rates, fetch prices, then rebuild the
PnL. The UI opens without waiting; reports show the previous results until the rebuild finishes.
Follow progress and failures in the worker output or Flower. An expired Saxo login can prevent its
price fetch; signing in again queues the full connection refresh (broker sync, FX, ledger ingest,
prices, then PnL). FX always comes before the ingest, which converts amounts with it.

Useful scripts in `backend/scripts/`: `sync_connection.py` (capture, `--full` re-pulls the
whole history), `ingest_connection.py` (map and reconcile from stored payloads), `rebuild_pnl.py`,
`rebuild_positions.py`, `sync_prices.py`, `sync_fx.py` and `connect_ibkr.py`.

## API contract

Interactive documentation is at `/api/schema`, with machine-readable JSON and YAML at
`/api/schema/openapi.json` and `/api/schema/openapi.yaml`. The interactive page (Redoc) loads its
script and fonts from a CDN, so it works on the API port and through the development server; the
production frontend's Content-Security-Policy blocks it, while the JSON and YAML still work there.
Every public operation has:

- Typed request and response models with field descriptions and realistic examples
- A stable, unique `operationId` for generated clients and agent tools
- Side-effect and error semantics in concise operation prose
- Explicit response status, media type, schema, and a tag

Shared metadata lives in `backend/app/openapi.py`. Update the generated artifacts after a contract
change:

```bash
cd frontend && npm run api:generate
```

The canonical generated document is `openapi/openapi.json`; frontend types are generated in
`frontend/src/api/schema.d.ts`. CI rejects stale generated artifacts.

## Tests and quality checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
cd frontend
npm run lint
npm run typecheck
npm run build
npm run test:ssr
```

Database integration tests (the PnL engine identities, positions, broker ingests) run against the
PostgreSQL database named by `TEST_DATABASE_URL`, each in its own temporary schema, so the dev
database works too. The user must be allowed to create and drop schemas. Without the variable,
those tests are skipped; CI provisions PostgreSQL and runs everything.

```bash
TEST_DATABASE_URL=postgresql://user:password@localhost/returns_portal uv run pytest
```

## Operations

- Liveness: `GET /api/health/live`
- Readiness: `GET /api/health/ready` (Postgres and Redis; returns 503 if either is unavailable)
- Daily health check: `returns-portal.verify_health` (`app/services/health_service.py`) looks for failed
  or stale broker syncs, expired or soon-expiring tokens, stale ECB rates, and portfolios whose
  reports the PnL rebuild has fallen behind on. It logs the problems and, when `ALERT_SMTP_HOST`, `ALERT_EMAIL_USER`
  and `ALERT_EMAIL_PASSWORD` are set, emails them
- Daily schedule (UTC, `backend/app/celery_app.py`): ECB FX at 04:15, broker syncs and ingest at 04:30,
  prices at 05:15, the PnL rebuild at 05:50 and the health check at 07:00 (`HEALTH_CHECK_CRON_HOUR`,
  `HEALTH_CHECK_CRON_MINUTE`); the token keep-alive runs every 20 minutes

## Running outside dev.sh

How and where you host Returns Portal is up to you; the project ships no deployment recipe. Whatever
you choose, the application consists of these processes, all reading `backend/.env`:

- API: `uvicorn app.api:app --host 127.0.0.1 --port 18020` from `backend/`. The API accepts only
  Host headers carrying its own port, `API_PORT` (default 18020), so the port uvicorn listens on, the
  API's `API_PORT` and the frontend's `API_PORT` (or `API_ORIGIN`) must all agree
- Celery worker and beat: `python -m celery -A app.celery_app worker` and `... beat` from `backend/`
- Frontend: `npm run build` once, then `node server.mjs` from `frontend/` with `NODE_ENV=production`
  and `FRONTEND_PORT` set; it proxies `/api/` to `http://127.0.0.1:$API_PORT` (default 18020), or to
  `API_ORIGIN` when that is set. It answers only to localhost and the host
  of `FRONTEND_ORIGIN` (read from the environment or `backend/.env`), refuses writes from other
  sites, and sends a strict Content-Security-Policy
- Optionally Flower (`python -m celery -A app.celery_app flower`); keep it private

On every update, apply the migrations and then the engine's SQL functions, in that order:

```bash
cd backend
DATABASE_URL="$(python -c 'from app.config import settings; print(settings.database_url)')" dbmate --no-dump-schema up
python scripts/apply_db_functions.py
```

The app has no login of its own: serve it only behind access control you trust. The settings that
change when it is served beyond localhost (`FRONTEND_ORIGIN`, `SAXO_REDIRECT_URI`, `ALLOWED_HOSTS`)
are at the end of `backend/.env.example`; every other setting and its default is in
`backend/app/config.py`. `APP_ENV` defaults to `production`, which keeps error details out of API
responses; `dev.sh` runs the API with `APP_ENV=development`, which returns exception messages in
500 responses, so never expose an instance started with `dev.sh` beyond your own machine.
