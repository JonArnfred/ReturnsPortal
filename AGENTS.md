# Agent and contributor notes

Returns Portal: self-hosted daily PnL, unitized returns and position-level attribution across
brokerage accounts (SaxoBank, Interactive Brokers), reconciled to the broker. These notes are the
rules and traps that are not obvious from the code. For everything else:

- `README.md`: what the project is and quick start; `CONTRIBUTING.md`: how to add a broker, ground
  rules for pull requests.
- `documentation/VISION.md`: domain model, accounting formulas, decisions and their reasons. Read it
  before changing accounting; update it when a decision is made or reversed.
- `documentation/DEVELOPMENT.md`: setup, running, API contract rules, tests.
- `documentation/BROKER_SETUP.md`: broker access, including the IBKR Flex query.

## Accounting rules

- Money and quantities are `Decimal` / `NUMERIC`, never float. Fractional shares are allowed.
- FX rates are reporting currency per one unit of foreign currency; always multiply.
- Every portfolio is booked in the reporting currency. Read it with
  `settings_service.reporting_currency()`, never from `settings` directly; changing it goes through
  `tasks.apply_reporting_currency` (FX, re-ingest from stored payloads, rebuild).
- Prices and FX are carried forward, never interpolated. Missing data becomes a recorded issue, never
  a dropped row; never inner-join prices or FX into the daily grid.
- The ledger is append-only (the one exception, provisional Saxo fills replaced by the booked trade, is
  in VISION.md 3.1) and ingest is idempotent (upserts on broker references). Derived tables
  (`pnl_days`, `portfolio_days`, `reconciliation_issues`, `positions`) are rebuilt, never edited.
- The attribution identities (VISION.md 4.1 and 4.2) are enforced by
  `backend/tests/test_pnl_engine_integration.py`. A change that breaks them is wrong even if the
  numbers look plausible; rerun it after any engine change.

## Code rules

- The PnL engine is SQL in `backend/db/functions/*.sql`, applied in file order by
  `scripts/apply_db_functions.py`. Keep SQL out of migrations and Python strings; other queries live
  in `app/services/*_sql.py`. No ORM.
- Migrations: one `create_<table>` file per table as of the first release, then a new file per
  change. Never edit an applied migration.
- Broker connectors (`app/connectors/<broker>/`): store every raw response in `broker_raw_payloads`
  before mapping; pydantic DTOs in `dto.py`; pure, tested `mapping.py`; persistence in `ingest.py`.
  Credentials are read-only, encrypted at rest, never logged or put in examples or fixtures.
- Every public endpoint has typed models, a stable `operationId`, a tag and a description. After an
  API change run `cd frontend && npm run api:generate`; CI rejects stale generated files.
- Anything that reveals holding size (NAV, market values, quantities) renders through `Amount`,
  `Quantity`, `DualMoney` or `useAmounts()` from `frontend/src/components/cells.tsx`, and NAV or value
  charts are marked `sensitive`, so the "hide amounts" toggle covers it. Prices, FX rates and
  percentages stay visible.
- Charts go through `frontend/src/charts/` (Highcharts); no other chart libraries or hand-made SVG.

## Traps

- IBKR's Flex Web Service throttles a token after about six requests in two minutes. Pull once, then
  work from the stored payloads (`scripts/ingest_connection.py` re-maps without contacting IBKR).
- `dev.sh` does not hot-reload the dev proxy (`frontend/server.mjs`) or the Celery worker; restart it
  after changing either or adding a task.
- The app has no login, so `frontend/server.mjs` answers only to localhost and the host of
  `FRONTEND_ORIGIN` (421 otherwise), and it and the API (`app/http.py`) refuse cross-site writes
  (403). A request that is refused for no obvious reason is usually one of these.
- Litestar reserves the handler argument name `state`; a query parameter called `state` needs
  another argument name and `Annotated[str | None, QueryParameter(name="state")]`. Declare query and
  path parameters with `FromQuery[...]` / `FromPath[...]`; the bare style is deprecated.
- MUI 9 `Stack` keeps its own `direction` and `spacing` props (`<Stack direction="row" spacing={1}>`),
  but other layout props such as `alignItems` and `justifyContent` go in `sx`. Never set
  `flexDirection` in `sx` on a `Stack`: `spacing` would still space it as a column.
- Server rendering must match the client: no block element inside `Typography` unless
  `component="div"`, and no `Date.now()` or `Math.random()` during render.
- Import the Highcharts wrapper as a named export (`import { HighchartsReact } from
  "highcharts-react-official"`); the default import breaks under Vite.

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
TEST_DATABASE_URL=postgresql://... uv run pytest   # each test uses its own schema; the dev database works
cd frontend && npm run lint && npm run typecheck && npm run build && npm run test:ssr
```
