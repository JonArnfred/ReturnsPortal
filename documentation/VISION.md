# Returns Portal — Design Document

The design record of Returns Portal: purpose, domain model, the accounting method and its formulas,
data sources, and the decisions with the reasoning behind them. It is written for contributors,
human or coding agent, and kept current: when a decision is made or reversed, it is updated here.
Sections marked **Decided** are settled; section 10 lists the decisions in one place. Sections 11
to 14 are implementation notes per area (the Saxo connector, FX and the engine, reporting start
dates, the IBKR connector), including what the brokers' real data turned out to look like.

## 1. Purpose

A single place to see a **daily profit-and-loss (PnL) and time-weighted return across all of an
investor's brokerage portfolios**, currently SaxoBank and Interactive Brokers (IBKR), connected with
read-only access. Precision is the point: every cent of daily change is explained and reconciles
to the broker, scoped to what a retail investor with a few accounts actually needs.

Core outputs:

- A **unit price (NAV per unit)** per portfolio and for the total, so returns are unaffected by
  deposits and withdrawals (unitized accounting).
- A **daily position-level attribution table**: price effect, FX effect, interaction effect,
  dividend effect, costs, trade flows, daily PnL, daily return, constant-currency return, total PnL.
- **Reconciliation** against what the broker reports, with discrepancies surfaced instead of hidden.

Non-goals (for now): trading or order placement, research tools, multi-tenant SaaS, tax reporting,
intraday data. A larger research platform is out of scope; this project deliberately stays small.

## 2. Principles

- **Ledger first.** The broker's transactions are the source of truth; broker snapshots are used
  to reconcile and seed, never as the primary source of PnL.
- **Every number explained.** The attribution identities in 4.1 and 4.2 are exact and enforced by
  tests; a mismatch with the broker is shown with its cause, not papered over.
- **No silent gaps.** Prices and FX are carried forward, never interpolated or inner-joined away;
  every gap becomes a recorded issue.
- **Rebuildable.** Raw broker responses are stored before they are interpreted, and every derived
  table can be rebuilt from the ledger, prices and FX.
- **Small.** One user per deployment, explicit SQL, no ORM. Section 8 lists the mistakes common in
  daily attribution engines that these principles are meant to prevent.

## 3. Domain model

### 3.1 Entities

- **Broker connection**: one per broker login (Saxo, IBKR). Holds encrypted read-only credentials
  and sync state (last sync, last successful sync, last error).
- **Portfolio**: the unit of return measurement. Default: one portfolio per broker account. A
  portfolio is booked in the user's **reporting currency** (chosen under Setup → Settings, else
  `REPORTING_CURRENCY`; see section 14); the broker's own base currency sits on the connection. A
  **portfolio group** ("Total") aggregates portfolios; it is unitized independently.
- **Security**: a listing, identified internally by `ticker:MIC` (ISO 10383 segment MIC, e.g.
  `SAP:XETR`, `SPY:ARCX`, `EQNR:XOSL`). Carries `currency_code` (trading currency),
  `price_currency_code` (quote currency, e.g. GBX = pence), ISIN, and broker identifiers
  (Saxo `Uic` + `AssetType`, IBKR `conid`). Cash is modelled as a security of asset class `cash`
  with price fixed at 1 in its own currency (see 4.4).
- **Ledger transaction**: the append-only source of truth for everything that changes a portfolio.
  Kinds (`LedgerKind` in `app/domain/models.py`): `trade`, `corporate_action`, `deposit`,
  `withdrawal`, `transfer`, `dividend`, `withholding_tax`, `commission`, `fee`, `tax`, `interest`,
  `lending_income`, `other`. Currency conversions and transfers between the client's own currency
  accounts are pairs of `transfer` legs. Each row has: portfolio, security (or cash currency), trade
  date, settlement date, quantity, price (local), gross local amount, cost amounts, base-currency
  amount as reported by the broker, the broker's own reference (unique per connection = idempotency
  key), and raw payload JSON. One exception to append-only: a provisional Saxo fill (from the order
  audit, so a trade shows before Saxo books it) is deleted once the booked trade for the same order
  arrives (`ledger_service.delete_superseded_fills`). Both come from stored raw payloads, so the
  ledger can still be rebuilt from them.
- **Daily price** per security per date (close, source). **Daily FX rate** per (date, base,
  foreign) = base units per 1 foreign unit.
- **Broker snapshot** per portfolio per date: positions (quantity, mark price, currency) and cash
  balances per currency, plus broker-reported account value. Used only for reconciliation and
  seeding, never as the primary source of PnL.
- **Position**: one holding episode of a security in a portfolio. It opens with the first trade
  that moves the quantity away from zero and closes when the quantity returns to zero; the next
  trade opens a new position. Identified by (portfolio, security, opened), so its id is stable
  across rebuilds. Carries share counts and the ledger money in the instrument and base currency
  (purchases, sales, invested cash, dividends, costs); valuation against the latest mark is a read
  model. `position_transactions` says which ledger rows make up each position. Decided: positions
  are a derived table with ids, rebuilt after every ingest, not a per-request computation.
- **Derived tables** (rebuilt by the engine, never edited by hand): `positions` and
  `position_transactions` (above), `pnl_days` (attribution rows, one per position per date),
  `portfolio_days` (NAV, flows, PnL, units, unit price, return), `reconciliation_issues`.

### 3.2 Conventions

- Quantities are signed: long positive, short negative. Trades: buy/close-short positive quantity,
  sell/open-short negative. Cash flows: money in positive.
- Quantities and money are `NUMERIC`, never bigint or float. Fractional shares are allowed (IBKR).
- FX convention: `fx_rate` = base currency per one unit of foreign currency, always multiply.
- Trade date drives returns; settlement date drives cash only.
- Display key `ticker:MIC` is computed, not stored.
- Timezone: dates are broker-local calendar dates as the broker reports them; the engine runs on
  a calendar-day grid (see 4.5).

## 4. Accounting method

### 4.1 Unitized portfolio accounting **(Decided)**

For each portfolio (and group) and each calendar day `t`:

```
NAV_t        = Σ market value of all positions incl. cash, in base currency, at end of day t
F_t          = net external flow on day t in base currency (deposits − withdrawals; transfers
               between own portfolios count at portfolio level but net to zero at group level)
PnL_t        = NAV_t − NAV_{t−1} − F_t
U_t          = (NAV_{t−1} + PnL_t) / units_{t−1}        -- ex-flow unit price
units_t      = units_{t−1} + F_t / U_t                  -- units issued/redeemed at today's price
r_t          = U_t / U_{t−1} − 1                         -- daily time-weighted return
```

Initialisation: `U_0 = 100`, `units_0 = NAV_0 / 100` on the portfolio's inception day.
Flows are struck at end-of-day (the day's PnL is earned by yesterday's units).

Derived: cumulative return `U_t / 100 − 1`, drawdown from running max of `U`, annualized return
`(1 + R)^(365.25 / days) − 1` only after a minimum of 30 days, index-100 series for charting.

### 4.2 Position-level daily attribution **(Decided, exact decomposition)**

For a position on day `t`, with prior quantity `q₀`, prior close `p₀` (local), prior FX `f₀`,
today's close `p₁`, today's FX `f₁`, and today's net traded quantity `Δq` at VWAP execution price
`pₓ` and execution FX `fₓ` (from the broker's reported base amount, **excluding** fees):

```
market_value_local = q₁ · p₁                     q₁ = q₀ + Δq
market_value_base  = q₁ · p₁ · f₁
trade_flow_base    = Δq · pₓ · fₓ                (signed cost of today's trades, ex fees)

price_effect       = q₀ · (p₁ − p₀) · f₀   +   Δq · (p₁ − pₓ) · fₓ
fx_effect          = q₀ · p₀ · (f₁ − f₀)   +   Δq · pₓ · (f₁ − fₓ)
interaction_effect = q₀ · (p₁ − p₀) · (f₁ − f₀)  +  Δq · (p₁ − pₓ) · (f₁ − fₓ)
dividend_effect    = D_local · f_book             (f_book = FX on the booking day, see 4.3)
cost_effect        = −(commissions + fees + withholding tax + financing) in base

daily_pnl_base     = price + fx + interaction + dividend + cost
identity           : daily_pnl_base − cost_effect == market_value_base − prev_market_value_base − trade_flow_base   (exact)

daily_pnl_local    = q₀ · (p₁ − p₀) + Δq · (p₁ − pₓ) + D_local
daily_return_pct   = daily_pnl_base / |prev_market_value_base|            (day 1: / |trade_flow_base|)
daily_return_constant_ccy_pct = daily_pnl_local · f₀ / |prev_market_value_base|
total_pnl_base     = running sum of daily_pnl_base per position
```

Why it is built this way: the traded-shares part is decomposed symmetrically (price at
execution FX, FX at execution price, explicit interaction), so the identity holds to the last
cent on days with trades, and costs are a separate effect rather than leaking into the FX effect.
`|…|` in denominators handles shorts.

Sum of `daily_pnl_base` over all positions of a portfolio (including cash positions) must equal
`PnL_t` from 4.1. This is the first reconciliation check and is enforced by tests.

### 4.3 Dividends, costs, interest

**Today:** dividends are booked on the **pay date** the broker reports, at that day's FX, as a
`dividend_effect` on the security with the cash arriving in the cash position (12.7). Withholding
tax is a `cost_effect`. Because the share price drops on the ex-date and the cash arrives only on
the pay date, NAV is understated in between; where the broker's account value includes dividend
accruals (IBKR), they are taken out before it is compared with the engine (section 14).

**Planned: accrual on the ex-date.** The intended model, not implemented yet:

- On ex-date, a `dividend_receivable` position is opened in the dividend currency for the gross
  amount (`shares held at ex-date × dividend per share`). It is a cash-like security with
  `p ≡ 1`, so it carries FX effect until paid. The `dividend_effect` for the equity position is
  booked that day at the ex-date FX.
- On pay date, the receivable closes: net cash arrives in the cash position and withholding tax
  becomes a `cost_effect`. Differences between accrued and paid amounts (rounding, tax rate,
  currency of payment) are booked on pay date and flagged if material.
- Data implication: the broker usually reports the dividend only at payment, so the ex-date
  amount per share must come from a reference source (yfinance `actions` for the security, or
  the broker's announcement feed where available) and is reconciled to the broker's cash on pay
  date. Until the ex-date amount is known, the accrual is estimated and the row is marked.
- Consequence: NAV does not dip on ex-date, and the engine NAV compares with the broker's account
  value including its accruals.

Fees, commissions, taxes and financing charges are separate ledger kinds and appear as
`cost_effect`; interest appears as `interest_effect`.

### 4.4 Cash as positions **(Decided)**

Each currency balance in a portfolio is a position in a `cash` security with `p ≡ 1`. The 4.2
formulas then give `price_effect = 0`, `interaction = 0`, and a genuine `fx_effect` on foreign
cash. This attributes cash FX revaluation, which is easily missed, and makes the
portfolio identity in 4.1 exact without special cases. An FX conversion is a pair of cash
transactions (sell currency A, buy currency B) with the execution FX recorded.

### 4.5 Calendar, gaps, fills **(Decided)**

- The engine runs on **every calendar day** from inception. Weekends and holidays exist as rows.
- Prices and FX are **forward-filled (last observation carried forward)**, never interpolated. A
  day with no new price and no FX change produces zero PnL. A holiday in Copenhagen with US
  markets open produces a genuine PnL row.
- A missing observation is a **data-quality issue**, recorded in `reconciliation_issues`, and
  the row is still produced with the carried value. Never inner-join prices or FX into the grid
  (that silently drops days).
- Days since inception and annualization use calendar days.
- Dashboard date: use one shared valuation date for NAV, daily totals, FX and contributors. The
  dashboard is where the current state is checked, so today counts once the rebuild has an
  observation for it; the response flags it `intraday` because its closes are the latest intraday
  prices until the markets close. Skip days with only carried values. A new close or foreign FX
  observation used by the rebuild, or account activity, qualifies even when PnL is zero.
  Base-currency cash-only portfolios need no market observation. Show the valuation date and a
  pending notice when newer calculated rows are excluded. This is not a guarantee of complete
  coverage for every exchange; carried prices for individual holdings and reconciliation findings
  remain visible in the detailed reports.

### 4.6 Corporate actions **(splits now, the rest later)**

Splits: the engine takes the ratio from the broker's corporate-action rows and adjusts `q₀` and
`p₀` on the effective date, so no fake price move is booked; splits the ledger never booked are
inferred (12.3). Mergers, spin-offs, symbol changes: recorded as ledger `corporate_action` rows
with explicit before/after legs; a same-day close of one security and open of another moves the
carried value across (12.4). Anything beyond that is handled manually until a pattern emerges.

## 5. Data sources

### 5.1 Brokers **(Decided: each user sets up their own read-only access)**

Ledger-first, snapshot-for-reconciliation. Each connector must deliver:

1. Transactions since a cursor (trades with quantity, price, currency, base amount, commission;
   cash movements typed as in 3.1; dividends; fees; interest; corporate actions).
2. A point-in-time snapshot: open positions with quantity and mark price, cash per currency,
   account value in base currency.
3. Optionally, historical end-of-day prices for held securities.

**IBKR**: the **Flex Web Service** (a per-query token, read-only, no gateway process) with one
Activity Flex Query; the sections it needs are listed in
[BROKER_SETUP.md](BROKER_SETUP.md#1-create-the-activity-flex-query). Queried by date range (at most
365 days per pull). IBKR provides `fxRateToBase` per row, its own daily marks and FX rates, and a
daily account value; section 14 has the details.

**SaxoBank**: **OpenAPI** with OAuth2 (authorization code + refresh). Endpoints used:
`port/v1/clients/me`, `port/v1/accounts/me`, `port/v1/positions`, `port/v1/netpositions`,
`port/v1/balances`, `port/v1/orders/me`, the Client Services reports `cs/v1/reports/trades` and
`cs/v1/reports/bookings`, the order audit `cs/v1/audit/orderactivities`, `ref/v1/exchanges` and
`ref/v1/instruments/details` for identifiers, and `chart/v3/charts` for price history. The developer
portal's 24-hour token is simulation only; reading a live account needs your own app approved for
live access.

Saxo OAuth redirect URL convention: the callback is handled by the Litestar API, so it must live
under `/api/`, which is the only prefix the frontend server (and any reverse proxy in front of it)
forwards to the backend. Register both:

- dev: `http://localhost:25183/api/connections/saxo/callback` (the frontend dev port must stay
  25183 for it to match)
- prod: `https://<domain>/api/connections/saxo/callback`, set as `SAXO_REDIRECT_URI`

The callback exchanges the code for tokens, stores them encrypted, and redirects the browser to
the Connections page (`/setup/connections`). Each authorization attempt uses a random, single-use
`state`.

### 5.2 Prices **(Decided)**

Primary: Saxo `chart/v3/charts` daily bars (`Horizon=1440`, split-adjusted, instrument currency;
newest 1200 bars without `Mode`, older pages with `Mode=UpTo` and `Time`; a delisted Uic answers
404). Verified: the latest close equals the broker's mark in the position snapshot for every held
position. For IBKR, its own daily marks come first (section 14). Fallback for instruments the
broker no longer knows or does not mark: yfinance (`app/connectors/yahoo`), symbol from ticker and
MIC (`NOVOb:XCSE` → `NOVO-B.CO`); a symbol that Yahoo does not know stays an error on the status
row until one is set in `security_price_sources.yahoo_symbol` (by SQL; there is no UI for it yet).
GBX/GBp/ZAc are divided by 100 into the major currency. Stored in `daily_prices` (OHLCV, source)
with one `security_price_sources` row per security (source, coverage, last error);
`price_service.sync_prices` backfills from 14 days before the first ledger row and re-covers the
last week on every run. Runs daily at 05:15 UTC after the broker sync (`returns-portal.sync_prices`),
or `scripts/sync_prices.py`. Served by `GET /api/prices/status` and `GET /api/prices`; the Data →
Prices page lists coverage and charts closes. Saxo's chart endpoint rate-limits bursts, hence the
0.4 s pause between requests.

Saxo tokens: access 20 minutes, refresh 60 minutes, rolling. `returns-portal.keep_tokens_alive`
runs every 20 minutes and refreshes when either token is within 30 minutes of expiry; a rejected
refresh marks the connection `expired` so the Connections page asks for a new login.

### 5.3 FX rates **(Decided: ECB crossed via EUR)**

**ECB** daily reference rates (free XML, working days, ~16:00 CET), crossed through EUR to the
base currency, stored as base-per-foreign, forward-filled. Always write the `base→base = 1`
row. Broker execution FX is taken from the ledger rows themselves (base amount ÷ local amount),
never from the daily table. The ECB publishes about 30 reference currencies, which covers the
currencies brokers settle retail accounts in; a fallback source would only be needed for a
currency the ECB does not publish, and that is out of scope.

## 6. Reconciliation (the "precision" part)

The checks, and where their results go:

1. Σ position PnL = ΔNAV − flows, per portfolio per day (must be exact; a test, not a runtime check).
2. Engine NAV vs broker-reported account value, per portfolio per snapshot day, in every PnL
   rebuild. A difference above 0.5% of the broker value (at least 1 unit) is a `nav_mismatch` issue
   in `reconciliation_issues`. A tighter limit mostly flags timing gaps between price-source closes
   and broker marks, which reverse the next day. Where the broker's own FX rates are known
   (`broker_fx_rates`, IBKR from Conversion Rates), the engine splits each day's difference exactly
   into `gap_fx` (holdings at ECB minus at broker rates), `gap_cash` and `gap_securities` (engine
   minus broker, both at broker rates) on `portfolio_days`; the Reconcile page shows the split per
   NAV mismatch, and per held currency the ECB rate, the broker's rate (plus its own quote, e.g.
   IBKR's USD per EUR) and that currency's effect. Saxo's rates are not captured yet. ECB and
   broker rates agree on average but can differ by a percent or two on single days for less liquid
   currencies, because the ECB fixes at 14:15 CET and IBKR at the close.
3. Ledger positions vs the broker's latest snapshot (quantity per security), at every ingest
   (`app/services/snapshot_reconcile.py`). The result is part of the ingest report (printed by
   `scripts/ingest_connection.py`, and the Celery task result shown in Flower); it is not stored as an
   issue yet.
4. Ledger cash per account and currency vs the broker's latest cash balances, the same way.
5. Engine daily PnL vs IBKR MTM PnL per position: planned. The MTM Performance Summary is captured
   but not mapped.
6. Missing or stale prices, missing FX and inferred splits are `missing_price`, `stale_price`,
   `missing_fx` and `inferred_split` issues in every rebuild. Failed or stale connector syncs and
   expiring tokens are reported by the daily health check (`returns-portal.verify_health`).

## 7. Architecture

Litestar API, Postgres via psycopg 3, Redis, Celery beat, dbmate SQL migrations, a React Router SSR
frontend and generated OpenAPI types. How the parts fit:

- **PnL engine in Postgres (Decided)**: SQL functions and CTEs that rebuild the derived tables
  (plain tables, no materialized views) per portfolio. Each function lives in its own file under
  `backend/db/functions/*.sql` (not inside migration strings), applied idempotently by
  `scripts/apply_db_functions.py` after dbmate migrations, so the SQL is readable and diffable.
  Tests run with pytest against an isolated schema in `TEST_DATABASE_URL`: golden fixtures (long,
  short, trade mid-day, FX-only day, split day, dividend, cash conversion, deposit on a big move
  day) plus the identity checks in 4.1 and 4.2 as single SELECTs. If SQL ever becomes limiting, the
  same tests carry over to a Python engine.
- **Backend `app/connectors/`**: one package per broker, each mapping raw payloads to ledger
  rows and snapshots. Raw payloads are stored so a mapping bug can be replayed without re-pulling.
- **Celery beat** (UTC, `app/celery_app.py`): `sync_fx` at 04:15 (the ingest converts with these
  rates) → `sync_all_connections` (sync and ingest every connection) at 04:30 → `sync_prices` at
  05:15 → `rebuild_pnl` at 05:50 → `verify_health` at 07:00, which mails problems when SMTP is
  configured. `keep_tokens_alive` runs every 20 minutes. The Saxo OAuth callback and the "Sync now"
  button queue `refresh_connection`, which runs the same chain for one connection at once.
- **Postgres**: ledger and reference tables via dbmate migrations. Derived data is one set of
  tables over all portfolios (no per-portfolio copies). Positions are rebuilt by every ingest;
  `pnl_days`, `portfolio_days` and `reconciliation_issues` by `rebuild_pnl` (the daily task, a
  connection refresh, or `POST /api/reports/rebuild`).
- **API**: `GET /api/reports/pnl` (paged with `page`, `per_page`, `order_by`, `order`, filtered with
  separate query parameters such as `portfolio_id`, `date_gte`, `date_lte` and `search`) returning
  `{data, meta:{total, order_by}}` with `*_base` and `*_local` pairs and `full_ticker`;
  `GET /api/reports/portfolio-days`; `GET /api/reconciliation/issues`. There is no built-in login:
  the app is single-user and is meant to run locally or behind access control the user chooses.
- **Frontend**: URL-as-state table (page, per-page, order, order-by, filters), stacked
  dual-currency cells (base on top, local in grey below), red/green only on the two return
  columns, a unit-price chart with drawdown, an attribution summary by currency and by portfolio,
  and a reconciliation page. Columns follow the attribution outputs listed in section 1, plus `costs`.
- **Secrets**: broker tokens encrypted at rest (key in `.env`), never logged, never in OpenAPI
  examples. Read-only scopes only.

## 8. Pitfalls to avoid

Mistakes that are easy to make in a daily attribution engine, and what this one does instead.

1. FX weekend gaps linearly interpolated while prices are forward-filled, producing fake
   weekend returns. Here: LOCF for both.
2. Inner joins on prices/FX that silently drop days and lump multi-day moves into one row.
   Here: calendar grid with carried values plus an issue row.
3. Execution FX back-solved from a base amount that includes fees, so commissions surface
   as FX effect. Here: costs are a separate effect and execution FX excludes them.
4. Quantities rounded to integers. Here: NUMERIC, fractional allowed.
5. Day-1 formulas that differ between local and base variants. Here: one symmetric decomposition.
6. Interaction effect computed for held shares only. Here: traded shares too, so the identity is exact.
7. Dividends booked on ex-date for PnL but on pay date for cash at a different FX. Here: one
   booking, on the pay date at that day's FX, until the ex-date accrual of 4.3 exists.
8. Cash FX revaluation never attributed, leaking out of the portfolio return. Here: cash positions.
9. Several unreconciled NAV computations (historical, live, KPI). Here: one engine, one NAV, plus
   an explicit comparison to the broker's number.
10. No tests on the PnL engine. Here: tests first.
11. Period boundaries snapped to the nearest date, not as-of. Here: as-of (last date ≤ requested).

## 9. Roadmap

In place: the schema and the SQL PnL engine with tests (section 12), FX and price ingestion with
carry-forward and issue logging, the web UI, the Saxo OpenAPI connector (section 11), the IBKR Flex
connector (section 14), and NAV reconciliation with its FX/cash/securities split.

Next: the ex-date dividend accrual (4.3), the IBKR MTM cross-check (6.5), storing the snapshot
position and cash checks as issues, Saxo's own FX rates, position transfers and richer corporate
actions (4.6), benchmark comparison, a monthly report, and more brokers.

## 10. Decisions

1. One reporting currency for every portfolio (section 14).
2. Dividends are booked on the pay date for now; accrual on the ex-date is the planned model (4.3).
3. FX from ECB crossed via EUR; no fallback source needed for the currencies in scope.
4. PnL engine in Postgres SQL (functions in `.sql` files rebuilding plain tables, CTEs), with the
   option to migrate to Python later if SQL becomes limiting. The constraints in 4.5 and 8
   apply regardless of language.
5. Own-account transfers are flows per portfolio and neutral at group level.
6. Each user sets up their own read-only API access to each broker.
7. Load all history each broker makes available, from account inception. If a broker's
   history is truncated, seed the earlier period from the first available snapshot and mark it.
8. Single user per deployment. No built-in login: run it locally or behind your own access control.
9. End-of-day prices only, no intraday.
10. No general ORM. Broker payloads are parsed into pydantic DTOs, mapped by a pure, tested mapping
    module into pydantic domain models, and persisted through explicit SQL in per-aggregate
    repository modules plus the generic `db.upsert_many` helper. Every raw broker response is
    stored in `broker_raw_payloads` so mappings can be replayed without re-pulling.
11. Saxo uses the plain authorization code grant with the app secret (not PKCE).
12. Positions are a derived table with stable ids, rebuilt after every ingest (3.1).
13. IBKR's own daily marks are the prices of the securities it holds (section 14).

Ledger-first with snapshot reconciliation is the working assumption. New decisions go here as
they are made.

## 11. Saxo connector notes

OAuth code grant end to end (`/api/connections/saxo/authorize` and `/callback`), tokens encrypted
at rest with Fernet (`SECRETS_ENCRYPTION_KEY`), automatic refresh before a sync, and the capture
stage of the sync: `port/v1/clients/me`, `accounts/me`, `positions`, `netpositions`, `balances`
(client and per account), open orders, the order audit log, and the Client Services reports
`trades` and `bookings` in yearly windows: from `SAXO_HISTORY_START` on the first sync (and with
`--full`), afterwards from 14 days before the last successful sync. Every response, including
failures, lands in `broker_raw_payloads`. Run it with `backend/scripts/sync_connection.py`
(synchronous) or the Celery task `returns-portal.sync_connection`; beat runs `sync_all_connections`
(sync and ingest for every connection) daily at 04:30 UTC, before the price and PnL jobs.

Mapping stage: `app/connectors/saxo/dto.py` (pydantic views of the payloads), `mapping.py` (pure,
tested), `ingest.py` (raw payloads to `exchanges`, `securities`, `ledger_transactions`,
`position_snapshots`, `cash_snapshots`, then reconcile). The ledger replay should match the broker
snapshot exactly on every position quantity and every account cash balance; the ingest report
lists any difference. Facts learned from the payloads, encoded in `mapping.py`'s docstring:

- Saxo symbols are `TICKER:mic` (lowercase MIC), so the `ticker:MIC` key needs no external map.
  `ref/v1/exchanges` maps Saxo exchange ids to MIC and operating MIC.
- The bookings report is the complete cash ledger. `BkAmountType` names the kind; `Cash Amount`
  rows are external flows unless the symbol is `CASHINTR` (transfer between the client's own
  currency accounts, including FX conversions). `Share Amount` rows are the cash legs of trades
  and are folded into the trade row.
- Splits, mergers and ticker changes arrive as zero-cash trade pairs with
  `TradeType = NotAvailable`; they become `corporate_action` rows.
- Each Saxo currency account is a separate `AccountKey`; the portfolio is the client, and cash is
  tracked per account currency.
- `port/v1/closedpositions` answers HTTP 400 for retail clients (end-of-day netting mode) and the
  Client Services `closedpositions` and `aggregatedAmounts` reports do not exist at the guessed
  paths; none of them is needed.
- Instrument details are missing for delisted instruments; those securities are derived from the
  trade row (symbol, name, currency from the booked share amount).

Investments views: `GET /api/ledger/transactions` (paged, filtered by kind, period, search),
`GET /api/positions` (holding episodes from the `positions` table, rebuilt by `rebuild_positions()`
after ingest: open and closed, split-adjusted average prices, dividends, return, ROI, annualized;
open episodes valued at the latest broker snapshot). The table shares the engine's conventions
(section 12): base amounts from the account on base-currency accounts, splits the ledger never
booked inferred from trade price vs close and stored as `basis_factor` per position and per linked
event, same-day events ordered by the broker's execution time, and corporate-action days that net
to zero open no position. `GET /api/positions/{id}` returns one position with trades and a daily
chart series, and `GET /api/ledger/cash-movements` the deposits, withdrawals and transfers with
legs paired (no page yet; it belongs in a future accounting menu, not under Investments). Frontend
pages: Trades, Positions, Dividends under a top-level Investments menu. Position ROI is the return
in base currency divided by the cash used to fund the episode: purchase amounts plus the
commissions, fees and taxes booked against those purchases (linked by `related_ref`); sell-side
costs reduce the return only.

Orders: working orders come from `port/v1/orders/me` (`FieldGroups=DisplayAndFormat,ExchangeInfo`;
the type is `OpenOrderType`), the full history from the audit log `cs/v1/audit/orderactivities`
(`ClientKey`, `FromDateTime`, `ToDateTime`, pulled in the same yearly windows as the reports; pages
with `__next`). Activity rows carry `AccountId` only, no symbol; statuses seen: Placed, Working,
Changed, DoneForDay, Fill (partial), FinalFill, Cancelled, with `SubStatus`
Requested/Confirmed/Rejected; fills carry cumulative `FilledAmount` and `AveragePrice`.
`order_service.merge_orders` folds the events into one row per order (latest event decides, first
Placed gives the placement time) and the working-orders list decides `is_open`. Stored in `orders`,
served by `GET /api/orders`, shown on the Orders page under Investments.

UI preferences: `user_preferences` is a key/value JSON store (`filters:<page>`), served by
`GET/PUT/DELETE /api/preferences`. Filters apply as they change (`useLiveFilters`: text fields
debounced, dropdowns and toggles at once; no Apply button). "Default" saves the current filters as
the page's default, "Reset" returns to it (or to the built-in one), "Clear saved default" forgets it;
`frontend/src/app/useFilterDefaults.ts` fills the URL from the saved default when a page opens
without filter parameters, so the URL stays the state.

Price history: Saxo's `chart/v3/charts` (`Uic`, `AssetType`, `Horizon=1440`, `Count` up to 1200,
`Mode=UpTo` with `Time` to page backwards) returns daily OHLCV for instruments the app can see; the
older `chart/v1` answers 404. It is the primary daily price source for Saxo, with yfinance as the
fallback for delisted instruments. `trade/v1/infoprices` gives a delayed live quote.

## 12. FX and the PnL engine

FX: `app/connectors/ecb` fetches the ECB reference-rate XML (full history since 1999 on the first run
or when the stored data is older than the 90-day feed, else the 90-day feed), stores it verbatim in
`ecb_reference_rates` and crosses it into `fx_rates` (base per one unit of foreign, one row per
published day, identity row for the base) for every base currency in `portfolios`. A base currency
seen for the first time gets the whole stored ECB history crossed (`fx_service.split_bases`), not
only the 90-day feed. Task `returns-portal.sync_fx` at 04:15 UTC (before the broker sync, whose
ingest converts with it), script `scripts/sync_fx.py`, page Data → FX rates.

Engine: `backend/db/functions/100_rebuild_pnl.sql` (`rebuild_pnl(portfolio_id, through)`), applied by
`scripts/apply_db_functions.py` (dev.sh runs it after dbmate). It rebuilds `pnl_days`, `portfolio_days`
and `reconciliation_issues` per portfolio; task `returns-portal.rebuild_pnl` at 05:50 UTC, script
`scripts/rebuild_pnl.py`, `POST /api/reports/rebuild` (button on the Returns page). It takes seconds
for several years of one account. Decisions taken while building it, all enforced by
`tests/test_pnl_engine_integration.py`:

1. Every ledger row has one base value used for both of its legs: `amount_account` when the account
   is in the base currency (Saxo's `AmountClientCurrency` carries ~0.0003% noise even for rows in
   the client currency), else the broker's `amount_base`. Trades, dividends and costs therefore
   cancel exactly between the security and the cash position, and Σ position PnL = ΔNAV − external
   flow holds to the last cent.
2. The two legs of a conversion between own accounts (same day, same booked currency and amount,
   opposite signs) are both valued at the base-currency leg, so the conversion spread is FX effect on
   the currency bought. Legs that do not net (unpaired, foreign-to-foreign) become a cost effect on the
   base cash, never a flow.
3. Quantities are carried on the split-adjusted basis of the price history: booked corporate actions
   that keep the position give a ratio; splits the ledger never booked (position closed before the
   split, e.g. a 20:1 split after the shares were sold) are inferred from trade price vs close,
   snapped to a whole ratio (`snap_split_ratio`) and recorded as an `inferred_split` issue.
4. A corporate action that closes one security and opens another the same day moves the carried
   value across (leaving side books no PnL, entering side books the difference to market).
5. Cash per currency is a position (4.4); a negative balance shows as short.
6. Prices: the day's close, else the last close, else the last ledger price (trade VWAP or
   corporate-action price); the newer observation wins. A price carried more than 7 days while held is a
   `stale_price` issue; no price at all carries the position at zero and is a `missing_price` issue.
7. Dividends are booked on the pay date the broker reports, not the ex-date of 4.3, until a per-share
   dividend feed exists. Withholding tax, commissions, fees and taxes are `cost_effect`, interest is
   `interest_effect`, lending income counts as dividend.
8. Effects are stored rounded to 8 decimals with the interaction effect defined as the residual, so
   the stored numbers satisfy the identities exactly; portfolio returns chain through
   `numeric_product` (18-decimal state), units = NAV / unit price by construction.

Read side: `app/services/pnl_service.py` and `pnl_sql.py`; `GET /api/reports/pnl` (paged attribution
rows, cash included, filters portfolio/kind/type/period/search), `GET /api/reports/portfolio-days`
(one portfolio, or all as "Total" unitized over the summed NAV and flows), `GET /api/reconciliation/issues`.
Pages: Reports → PnL and Returns, Data → FX rates and Reconcile, and the Dashboard read the API.
The dashboard uses `GET /api/reports/dashboard`: a read-only database snapshot with NAV history,
daily totals, FX including cash, portfolio returns, contributors and all recorded issue counts.
It uses the latest shared reporting date, flags portfolios without calculated data, and leaves totals
unavailable when base currencies differ or coverage does not overlap. Refresh reloads stored results;
it does not sync brokers or rebuild reports.

## 13. Portfolio reporting start date **(Decided)**

An optional `portfolios.reporting_start_date`, editable on Investments → Portfolios, establishes
an inclusive reporting boundary at the beginning of that broker-local calendar day. Blank restores
full history; future dates are rejected. PATCH only changes supplied fields, independently of the
portfolio's display name. No broker history, ledger rows, position ids or original acquisition costs
are deleted or rewritten, and changing the date requires no accounting rebuild.

The reporting views in `backend/db/functions/300_reporting_views.sql` retain full-history engine
results underneath. Holdings and cash carry in at the prior close. The displayed unit index starts
at 100 at that opening boundary, then includes the selected day's return; cumulative returns,
drawdowns and position PnL restart there. A loss on the first day counts toward drawdown. Later
page-level date filters narrow the report but cannot reveal dates before the portfolio boundary.

Positions open at the boundary remain visible even if bought earlier. Period returns use signed
opening value plus subsequent trade cash, dividends and costs; invested capital uses absolute
opening value plus subsequent purchases and their funding costs. Annualization starts at the later
of the position's opening and the reporting date. Position ids, actual opening dates, lifetime
average purchase/sale prices and original acquisition cash remain available. Detail charts compute
holdings from the complete ledger before cropping, so splits and carry-in shares stay correct.
Missing opening valuations or current marks yield unavailable returns, never assumed zero gains.
Positions closed before the boundary are omitted; later income still appears in the activity and
PnL reports. Clearing the setting restores the original view.

The boundary applies to dashboard history and returns, attribution, positions, transactions,
cash movements, historical orders, and reconciliation findings. Working orders remain visible
regardless of placement date. Current cash, holdings and broker NAV remain actual balances.

In combined reports each portfolio enters on its own first included day. On subsequent group days,
its opening NAV is recorded as a start-of-day capital contribution, not PnL. Daily group return is
summed PnL divided by summed opening NAV (including that entering capital); ordinary broker flows
keep the engine's end-of-day convention. Different base currencies are not summed. The dashboard
continues to use the latest common reporting day and exposes missing coverage.

Regression coverage is in `tests/test_reporting_start_date_integration.py` alongside the
engine and position tests.

## 14. IBKR Flex connector notes

Implemented in `app/connectors/ibkr/`, mirroring Saxo: `client.py` (the two-step Flex Web Service
download with polling), `dto.py` (statement XML to attribute rows, pydantic views), `mapping.py`
(pure, tested), `sync.py` (capture), `ingest.py` (map, persist, reconcile), `connect.py` (token and
query id storage; there is no OAuth). `app/connectors/registry.py` dispatches tasks and scripts on
`broker_connections.broker`; `scripts/connect_ibkr.py` creates the connection from `IBKR_FLEX_TOKEN`
and `IBKR_FLEX_QUERY_ID`, and `POST /api/connections/ibkr` does the same from the Connections page.
The query id lives in `broker_connections.query_id`; the token is the encrypted access token with
the expiry chosen at generation time (a year at most; the keep-alive task marks the connection
expired when it lapses, since Flex tokens cannot be refreshed).

Facts about the Flex Web Service and its statements:

- Two GETs per pull: `SendRequest` (`t`, `q`, `v=3`) returns a reference code, `GetStatement` returns
  the report once generated (error 1019 while it is building, 1018 when throttled; six requests in
  two minutes were enough to be throttled). The period override `p=N` works; the date override
  `fd`/`td` works only when `td` is a business day (a weekend end date answers 1003). The sync uses
  `p` for accounts younger than a year and `fd`/`td` windows of 365 days ending on a weekday otherwise.
- The first sync pulls a 7-day statement to read Account Information (base currency, opening date),
  then the history from the opening date. Later syncs pull the days since the last successful sync
  plus three of overlap; the ingest collapses repeats on IBKR's identifiers.
- One account (`U…`) with a balance per currency and one base currency. Each ledger row's account
  currency is its own currency and the account amount equals the local amount.
- **Reporting currency (Decided).** The user reports in one currency for every broker: the one
  chosen under Setup → Settings (`app_settings`), else `REPORTING_CURRENCY`. Changing it re-books
  every portfolio from the stored payloads (`tasks.apply_reporting_currency`); Saxo pins it to the
  Saxo client currency. A portfolio has no base currency of its own: `portfolios.base_currency`
  always holds the reporting currency (the SQL engine reads its base from there), and the broker's
  base currency lives on `broker_connections.base_currency`. Base amounts are converted with the
  forward-filled ECB rate of the day (`mapping.BaseConversion`); IBKR's own `fxRateToBase` is used
  only when the broker's base equals the reporting currency, since it converts into the broker's
  base. The IBKR NAV series and the position marks are converted the same way, so `broker_value`
  and the reconciliation compare like with like. The Saxo ingest refuses to run when the client
  currency differs from the reporting currency, because its booked client-currency amounts are
  still taken as base amounts.
- Trades at execution level: `proceeds` before commission, `ibCommission` in its own currency; a
  trade is a `trade` row plus a linked `commission` row. Currency conversions are CASH trades
  (e.g. `EUR.USD`) and become two `transfer` legs, so the engine books the spread as a conversion cost.
- Cash transactions are booked on `reportDate`; a dividend's `dateTime` is the pay date and IBKR's
  NAV reflects it only from the report date. Deposits are typed `Deposits/Withdrawals` (sign decides).
- Open Positions (summary level) give the snapshot; the Cash Report per currency gives ending cash;
  NAV in Base gives the account value per day, stored as the `''` account-key cash snapshot the
  engine reads as `broker_value`, minus dividend and interest accruals (the ledger books those when
  paid). MTM Performance Summary, Statement of Funds and Change in Dividend Accruals are captured
  but not mapped yet; Conversion Rates become `broker_fx_rates` (section 6).
- **Prices (Decided):** IBKR's own daily marks are the closes of the securities it holds. The Flex
  query includes Prior Period Positions: one row per position held at the previous close, per
  business day, with that day's closing mark (`date`, `price`; it matches Open Positions'
  `markPrice`). The opening day of a position has no such row, so a trade's `closePrice` (IBKR's
  close of the trade date) covers it, and Open Positions covers the statement's last day. The
  ingest writes these marks into `daily_prices` with source `ibkr`, and the Yahoo refresh never
  overwrites a marked day. Symbol changes keep the conid, so marks follow a renamed listing. Yahoo
  (`listingExchange` mapped to a MIC; minor-unit quotes such as GBX normalised) fills the days
  without a mark. Why: a European-listed ETP that tracks a US index closes at 17:30 CET while IBKR
  marks it later in the US session, so Yahoo closes can sit several percent off IBKR's NAV and
  reverse the next day; ECB vs IBKR FX explains far less of such a gap. With the marks, engine and
  IBKR security values agree to rounding, and what remains is ECB vs IBKR FX. Marks are as of their
  day, so days up to a booked quantity-changing corporate action keep the split-adjusted Yahoo
  close. `scripts/sync_connection.py <id> --full` re-pulls the whole history once after a section
  is added to the query.
- Account Information is stripped to account, currency, name, type and dates before it is stored.

Not covered yet: position transfers (recorded as `transfer` rows with quantity, no position opened),
corporate actions (mapped generically), the MTM cross-check per position.
