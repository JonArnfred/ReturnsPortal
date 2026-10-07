# Connecting your brokers

Returns Portal only ever needs read access. This page explains how to give it that access for each
supported broker. Credentials are stored encrypted with `SECRETS_ENCRYPTION_KEY` (see the
[README](../README.md#quick-start)) and are never logged.

## Interactive Brokers (Flex Web Service)

IBKR is read through the Flex Web Service: you define one **Activity Flex Query** in Client Portal,
generate a **Flex Web Service token**, and give Returns Portal the token and the query's id. The
token can only download reports; it cannot trade or move money. There is no gateway process to
keep running.

### 1. Create the Activity Flex Query

In Client Portal, open **Performance & Reports → Flex Queries** and create a new **Activity Flex
Query** (the name is up to you). Add the sections below. Selecting all fields in each section is
the simplest choice and is what the connector is tested with; unknown fields are ignored.

| Section in Client Portal | Options | Used for |
|---|---|---|
| Account Information | | Account id, base currency and opening date (the first sync pulls history from it) |
| Trades | Execution | Trades, commissions and currency conversions; `closePrice` is the opening day's mark |
| Cash Transactions | Detail; all types | Deposits, withdrawals, dividends, withholding tax, interest, fees |
| Corporate Actions | | Splits, mergers and other actions that change holdings |
| Transfers | | Position and cash transfers in and out of the account |
| Open Positions | Summary | Positions and marks on the statement's last day, checked against the ledger |
| Cash Report | Currency breakout | Cash per currency, checked against the ledger |
| Net Asset Value (NAV) in Base | | IBKR's daily account value, which every day's NAV is reconciled against |
| Financial Instrument Information | | Symbols, ISINs, listing exchanges and currencies |
| Prior Period Positions | | IBKR's daily mark for each held position, used as the day's price |

Strongly recommended:

- **Prior Period Positions** (in the table above). Without it, prices come from Yahoo, whose
  closes can differ from IBKR's marks by several percent on some instruments (a European-listed
  product that tracks a US index is marked by IBKR after the US session, for instance), and
  reconciliation shows those days as mismatches.
- **Include Currency Rates: Yes** in the query's general configuration. This adds IBKR's daily FX
  rates, which let the Reconcile page split a NAV difference into ECB vs IBKR FX, cash and prices.

Optional: Mark-to-Market Performance Summary, Statement of Funds and Change in Dividend Accruals
are captured when present but not used yet.

General configuration:

| Setting | Value |
|---|---|
| Format | XML |
| Period | Any, e.g. Last 365 Calendar Days (each sync requests its own date range) |
| Breakout by Day | No |
| Date format | `yyyy-MM-dd` or `yyyyMMdd` |
| Time format | `HH:mm:ss` or `HHmmss` |
| Date/time separator | `;` (semicolon) |
| Include Canceled Trades | Either; cancelled executions are skipped |
| Display Account Alias in Place of Account ID | No |

Save the query and note its **Query ID**, the number shown next to it in the list.

### 2. Generate the Flex Web Service token

On the same Flex Queries page, open the **Flex Web Service Configuration**, enable the service and
generate a token. Choose a validity (up to a year) and note the date: Flex tokens cannot be
refreshed, so the connection is marked expired when it lapses, and you generate a new token and
reconnect. If you restrict the token to IP addresses, include the address the app runs from.

### 3. Connect

Either open **Setup → Connections** in the app, choose **Connect** for Interactive Brokers and
enter the token, the query id and the token's expiry date, or put them in `backend/.env` and run
the connect script:

```bash
# backend/.env
IBKR_FLEX_TOKEN=...
IBKR_FLEX_QUERY_ID=...
IBKR_HISTORY_START=          # optional, YYYY-MM-DD; defaults to the account's opening date
```

```bash
cd backend
uv run python scripts/connect_ibkr.py 2027-10-01 --sync   # the token's expiry date; --sync pulls right away
```

The first sync pulls a short statement to learn the account's opening date, then the whole history
in windows of at most 365 days. Later syncs pull only the days since the last one, with a few days
of overlap; importing the same rows twice changes nothing.

### Good to know

- **Throttling.** The Flex Web Service throttles a token after a handful of requests in quick
  succession (six within two minutes was enough). Avoid repeated manual syncs; the scheduled daily
  sync needs only a couple of requests.
- **Changing the query later.** New sections only arrive for the dates a sync requests. After
  adding one, pull the history once more:

  ```bash
  cd backend
  uv run python scripts/sync_connection.py <connection id> --full
  uv run python scripts/ingest_connection.py <connection id>
  ```

- **Reporting currency.** IBKR reports in your account's base currency. When that differs from
  your reporting currency (Setup → Settings), amounts are converted with ECB rates, the same way for the ledger and for
  IBKR's own account value, so the two stay comparable.

## SaxoBank (OpenAPI)

Saxo is read through its OpenAPI with OAuth, which means registering your own application with Saxo:

1. Create an application on Saxo's developer portal with the authorization code grant. Live
   (non-simulation) access requires Saxo to approve the application.
2. Register the redirect URL. The callback is served by the API under `/api/`:
   `http://localhost:25183/api/connections/saxo/callback` when running with `dev.sh`, or
   `https://<your host>/api/connections/saxo/callback` elsewhere.
3. Fill in `backend/.env`:

   ```bash
   SAXO_APP_KEY=...
   SAXO_APP_SECRET=...
   SAXO_ENVIRONMENT=live          # or sim
   SAXO_REDIRECT_URI=http://localhost:25183/api/connections/saxo/callback
   SAXO_HISTORY_START=2010-01-01  # how far back to import
   ```

4. Open **Setup → Connections**, choose **Connect** for Saxo and sign in at Saxo. The app keeps the
   session alive with refresh tokens; when Saxo ends it, use **Reconnect** on the same page.

Saxo books every account in your client currency, so with a Saxo connection the reporting currency
must be that client currency: Setup → Settings only offers it, and the ingest refuses to run otherwise,
because Saxo's booked amounts are taken as reporting-currency amounts.
