# Contributing to Returns Portal

Contributions are very welcome. Open an issue first for anything larger than a small fix, so we
can agree on the approach before you invest the time. Security problems go through
[SECURITY.md](SECURITY.md), not a public issue.

Never paste account numbers, amounts, holdings or credentials into an issue, a pull request or a
test fixture. Use the "hide amounts" toggle for screenshots, and build fixtures from anonymized
payloads.

[documentation/DEVELOPMENT.md](documentation/DEVELOPMENT.md) covers setup, running and the checks;
[documentation/VISION.md](documentation/VISION.md) the accounting model and the decisions behind it.

## Adding a broker

Each broker connector turns one broker's data into the shared ledger; the engine, reports and
reconciliation then work on it unchanged, and the UI needs only the small additions in step 6.
Good candidates are brokers with a read-only API or a reliable export, for example Nordnet,
DEGIRO, Trading 212, Charles Schwab, Fidelity or Swissquote, or a generic CSV import for brokers
without an API.

A connector lives in `backend/app/connectors/<broker>/` and follows the existing two
(`saxo/` and `ibkr/`; the IBKR one is the smaller and easier to read):

1. **`client.py` and `sync.py` (capture).** Fetch with read-only credentials and store every
   response in `broker_raw_payloads` (`connection_service.record_raw_payload`) before mapping
   anything. Sync incrementally with some overlap; respect the broker's rate limits.
2. **`dto.py`.** Pydantic models of the broker's payloads; unknown fields ignored, amounts as `Decimal`.
3. **`mapping.py` (pure, no I/O).** Turn DTOs into the domain records in `app/domain/models.py`:
   `SecurityRecord`, `LedgerRow` (kinds such as `trade`, `dividend`, `withholding_tax`,
   `commission`, `fee`, `interest`, `transfer`, `corporate_action`, `deposit`, `withdrawal`),
   `PositionSnapshotRow` and `CashSnapshotRow`. If the broker reports a daily account value, map it
   to the account-level cash snapshot the engine reconciles against. Optional extras: the broker's
   own FX rates (`BrokerFxRate`) and price marks, which sharpen reconciliation.
4. **`ingest.py`.** Read the stored payloads, map, and persist with the upserts in
   `app/services/ledger_service.py`; it must be idempotent (keyed on the broker's references). Then
   rebuild positions and run the shared snapshot reconciliation.
5. **Migration.** The database only accepts known brokers: add a migration that widens the
   `broker` check on `broker_connections`. If the connector brings the broker's own price marks,
   widen the `source` check on `daily_prices` too and add the source to `PriceSource` in
   `app/domain/models.py`.
6. **Wire it up.** Register the connector in `app/connectors/registry.py`, add a connect endpoint in
   `app/routes/connections.py`, its display name in `frontend/src/app/brokers.ts`, and a card on the
   Connections page.
7. **Tests.** Mapping tests built from recorded, anonymized payloads, and an ingest integration test
   showing the ledger replays to the broker's own cash balances and positions.

The bar for a connector: read-only access only, credentials never logged or committed, no floats
for money, raw payloads stored before mapping, and an ingest that can be rerun without changing
the result. Section 14 of [VISION.md](documentation/VISION.md) records what was learned building
the IBKR connector, which is a good guide to the pitfalls (dates, currencies, fees).

## Other ways to help

- Accounting edge cases with a hand-worked test: spin-offs, mergers, return of capital, bonds,
  options, short positions.
- Price and FX sources, trading calendars, and better handling of instruments Yahoo does not know.
- Reports and charts: sector and currency exposure, benchmarks, contribution over longer periods.
- Documentation, and trying the setup on a fresh machine and telling us where it hurts.

## Ground rules

- Money and quantities are `Decimal`/`NUMERIC`; FX rates are reporting currency per one unit of
  foreign currency, always multiplied.
- The ledger is append-only and derived tables are rebuilt, never edited by hand. Engine SQL lives
  in `backend/db/functions/`, not in Python strings or migrations.
- A change that breaks the attribution identities is wrong even if the numbers look plausible; run
  the engine integration tests.
- Every public endpoint has typed models, a stable `operationId` and docs; regenerate the
  frontend types with `npm run api:generate` after an API change.
- Before opening a pull request, run the checks:

  ```bash
  uv run ruff check . && uv run ruff format --check . && uv run mypy
  TEST_DATABASE_URL=postgresql://... uv run pytest
  cd frontend && npm run lint && npm run typecheck && npm run build && npm run test:ssr
  ```

  Database integration tests create and drop their own schema in `TEST_DATABASE_URL` and are
  skipped without it.

[AGENTS.md](AGENTS.md) holds the rules and traps that are not obvious from the code. It follows the
common `AGENTS.md` convention that many coding agents read (the one-line `CLAUDE.md` imports it for
Claude Code), and it works just as well as a checklist for people.
