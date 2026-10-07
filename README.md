# Returns Portal

Self-hosted daily PnL, time-weighted returns and position-level attribution across all your
brokerage accounts, in one reporting currency, reconciled to what each broker reports.

Every broker shows its own account in its own way. Returns Portal pulls your accounts through
read-only access into one append-only ledger, values every position every day, and explains each
day's change in value as price, FX, dividends, costs and flows. Where its numbers differ from the
broker's, it says so and shows why, instead of quietly adopting the broker's figure.

> **Status:** early and actively developed. It is used daily with SaxoBank and Interactive Brokers
> accounts, but it is a single-user tool without a login, the schema still changes, and the
> numbers are only as good as the data behind them. Always check against your broker. Nothing
> here is financial or tax advice.

## What it does

- **Read-only broker connections.** SaxoBank through its OpenAPI (OAuth) and Interactive Brokers
  through the Flex Web Service. Every raw broker response is stored before it is interpreted, so
  the ledger can always be rebuilt and audited.
- **One ledger across brokers.** Trades, dividends, withholding tax, fees, interest, currency
  conversions, corporate actions, deposits and withdrawals, keyed on the broker's own references,
  so re-imports never duplicate anything. Fractional shares and multi-currency cash are first class.
- **Unitized returns.** A unit price (NAV per unit) per portfolio and for the total, so deposits
  and withdrawals do not distort performance; cumulative return, drawdown and annualized return.
- **Daily attribution per position.** Price, FX, interaction, dividend, interest and cost effects
  that add up exactly to the day's PnL, which in turn adds up exactly to the change in NAV minus
  flows. These identities are enforced by tests, not approximated.
- **Reconciliation.** The engine's NAV is compared with the broker's account value every day, and
  each import checks the replayed ledger's positions and cash against the broker's latest snapshot.
  Where the broker's own FX rates are known (IBKR), a NAV difference is split into FX (ECB rate vs
  the broker's rate, per currency), cash, and prices/holdings, so a mismatch points at its cause.
- **Prices and FX.** IBKR's own daily marks, Saxo price history, Yahoo as the fallback, and ECB
  reference rates. Prices and rates are carried forward, never interpolated; every gap becomes a
  recorded issue rather than a silently dropped row.
- **A privacy toggle.** One click hides every figure that reveals holding size (NAV, market values,
  quantities) while keeping prices, rates and percentages visible, for screen sharing.

## How it works

```
Broker API ──► raw payloads ──► pure mapping ──► ledger ──► SQL PnL engine ──► API ──► web UI
 (read-only)    (stored as-is)   (tested DTOs)    (append-   (Postgres functions:     (Litestar,  (React Router
                                                   only)      daily positions,         OpenAPI)    SSR, MUI,
                                                              NAV, units, issues)                  Highcharts)
```

- **Backend:** Python 3.12, Litestar, psycopg 3 with explicit SQL (no ORM), Celery and Redis for
  syncs, dbmate migrations.
- **PnL engine:** plain Postgres SQL in `backend/db/functions/`. It rebuilds the derived tables
  (`pnl_days`, `portfolio_days`, `reconciliation_issues`) from the ledger, prices and FX, so a
  fix to the engine or the data is one rebuild away.
- **Frontend:** React 19, React Router 7 with server-side rendering, MUI and Highcharts, typed
  from the generated OpenAPI document.

The accounting in short: each day `NAV_t = Σ positions incl. cash` in the reporting currency,
`PnL_t = NAV_t − NAV_{t−1} − flows_t`, and the unit price moves with `PnL_t` only, while flows
issue or redeem units at that price. All amounts are `Decimal`/`NUMERIC`, never floats. The full
model, the formulas and the reasoning behind each decision are in
[documentation/VISION.md](documentation/VISION.md).

## Supported brokers

| Broker | Access | Imported | Prices |
|---|---|---|---|
| SaxoBank | OpenAPI, OAuth (register your own app at Saxo's developer portal) | Trades, cash bookings, corporate actions, positions, balances, orders | Saxo price history, Yahoo for delisted instruments |
| Interactive Brokers | Flex Web Service: a read-only token and an Activity Flex Query | Trades, cash transactions, corporate actions, transfers, positions, cash, daily NAV, FX rates | IBKR daily marks, Yahoo for unmarked days |

How to set up access for each (the IBKR Flex query, the Saxo app) is described in
[documentation/BROKER_SETUP.md](documentation/BROKER_SETUP.md). Your broker is missing? That is the
most useful contribution you can make; see [Adding a broker](CONTRIBUTING.md#adding-a-broker).

## Quick start

You need Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 24 (see `.nvmrc`),
PostgreSQL (CI uses 17), Redis and [dbmate](https://github.com/amacneil/dbmate).

```bash
git clone <this repository> returns-portal && cd returns-portal

# Python environment in .venv (set UV_PROJECT_ENVIRONMENT first to keep it elsewhere)
uv sync --locked
(cd frontend && npm ci)

# Configuration
cp backend/.env.example backend/.env
uv run python backend/scripts/generate_encryption_key.py   # paste into SECRETS_ENCRYPTION_KEY
```

In `backend/.env`, fill in the Postgres and Redis settings, set `REPORTING_CURRENCY` to the
currency you think in (e.g. `EUR`, `USD`, `DKK`; any currency with an ECB reference rate; you can
change it later under **Setup → Settings**, which recalculates everything), and add the
credentials of the brokers you use (`SAXO_*` and/or `IBKR_FLEX_*`; see
[BROKER_SETUP.md](documentation/BROKER_SETUP.md) for how to get them). Then:

```bash
./dev.sh
```

`dev.sh` applies the migrations and the SQL engine, then starts the API (port 18020), the web UI
(<http://localhost:25183>), a Celery worker with its scheduler, and Flower. Connect a broker under
**Setup → Connections**; the first sync imports the history, fetches prices and FX, and builds
the reports.

> **Security:** the app has no login of its own and holds read-only access to your accounts.
> Keep it on your machine, or put it behind access control you trust (a VPN, or authentication
> in your reverse proxy) before exposing it anywhere. Broker tokens are encrypted at rest with
> `SECRETS_ENCRYPTION_KEY` and never logged. [SECURITY.md](SECURITY.md) describes what the app
> protects and how to report a vulnerability.

How you host it beyond your own machine is up to you; [DEVELOPMENT.md](documentation/DEVELOPMENT.md#running-outside-devsh)
lists the processes and the update steps any setup needs.

## Contributing

Contributions are very welcome, new broker connectors most of all. [CONTRIBUTING.md](CONTRIBUTING.md)
describes how to add a broker, other ways to help, and the ground rules and checks for a pull request.

## Repository layout

```
backend/
  app/connectors/     one package per broker (saxo, ibkr), plus ECB FX and Yahoo prices
  app/services/       ingest persistence, read models, explicit SQL (*_sql.py)
  app/routes/         Litestar endpoints (OpenAPI at /api/schema)
  db/migrations/      dbmate schema migrations
  db/functions/       the PnL engine in SQL, applied in file order
  tests/              unit tests and Postgres integration tests
frontend/src/         React Router SSR app: pages, tables, charts, generated API types
openapi/openapi.json  the generated API contract
documentation/        VISION (design and accounting), BROKER_SETUP, DEVELOPMENT
```

## Documentation

- [VISION.md](documentation/VISION.md): purpose, domain model, accounting formulas, data sources,
  decisions and their reasons.
- [BROKER_SETUP.md](documentation/BROKER_SETUP.md): setting up read-only access for each broker,
  including the IBKR Activity Flex Query.
- [DEVELOPMENT.md](documentation/DEVELOPMENT.md): detailed setup, API contract rules, caching,
  quality checks, running it outside `dev.sh`.

## License

Returns Portal is released under the MIT licence; see [LICENSE](LICENSE).

The charts use [Highcharts](https://www.highcharts.com/), which is not open source: it is free for
personal and other non-commercial use under its own licence, and commercial use needs a licence
from Highsoft. Returns Portal is meant for personal use; if you use it commercially, you need a
Highcharts licence for that use (the MIT licence covers only this project's own code).
