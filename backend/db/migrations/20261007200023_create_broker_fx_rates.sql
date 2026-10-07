-- migrate:up
-- The broker's own FX rate per currency and day, in the portfolio's reporting currency per one unit
-- (the app's convention: always multiply). Derived from broker payloads by the ingest; rebuilt, never
-- hand-edited. For IBKR: its Conversion Rates into the account base, crossed into the reporting
-- currency with the same ECB rate the broker NAV is converted with.
CREATE TABLE IF NOT EXISTS broker_fx_rates (
    portfolio_id bigint NOT NULL REFERENCES portfolios (id) ON DELETE CASCADE,
    rate_date date NOT NULL,
    currency char(3) NOT NULL,
    rate numeric(24, 12) NOT NULL,           -- reporting currency per one unit of currency
    quote_currency char(3) NOT NULL,         -- the currency the broker quotes its own rate in (IBKR: account base)
    quote_rate numeric(24, 12) NOT NULL,     -- the broker's own rate: quote_currency per one unit of currency
    fetched_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (portfolio_id, rate_date, currency)
);

-- migrate:down
DROP TABLE IF EXISTS broker_fx_rates;
