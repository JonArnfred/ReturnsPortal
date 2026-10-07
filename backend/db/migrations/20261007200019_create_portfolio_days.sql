-- migrate:up
-- Derived tables written by the SQL PnL engine (backend/db/functions/*.sql). Rebuilt per portfolio
-- from the ledger, daily_prices and fx_rates; never hand-edited.

-- Unitized portfolio accounting per calendar day (documentation/VISION.md 4.1).
CREATE TABLE IF NOT EXISTS portfolio_days (
    portfolio_id bigint NOT NULL REFERENCES portfolios (id) ON DELETE CASCADE,
    day date NOT NULL,
    base_currency char(3) NOT NULL,
    nav numeric(24, 8) NOT NULL,
    positions_value numeric(24, 8) NOT NULL,
    cash_value numeric(24, 8) NOT NULL,
    nav_prev numeric(24, 8) NOT NULL,
    flow numeric(24, 8) NOT NULL,         -- external: deposits minus withdrawals
    daily_pnl numeric(24, 8) NOT NULL,    -- sum of the positions' daily PnL
    daily_return_pct numeric(20, 12),
    unit_price numeric(24, 12) NOT NULL,
    units numeric(28, 12) NOT NULL,
    cumulative_return_pct numeric(20, 12) NOT NULL,
    drawdown_pct numeric(20, 12) NOT NULL,
    broker_value numeric(24, 8),          -- broker-reported account value on snapshot days
    -- Where an engine-vs-broker NAV difference comes from, on days with a broker value and broker FX
    -- rates for every held currency: nav - broker_value = gap_fx + gap_cash + gap_securities exactly.
    broker_cash_value numeric(24, 8),     -- broker-reported cash on snapshot days
    gap_fx numeric(24, 8),                -- engine holdings at ECB rates minus at the broker's rates
    gap_cash numeric(24, 8),              -- engine cash minus broker cash, both at the broker's rates
    gap_securities numeric(24, 8),        -- engine securities minus broker securities, at the broker's rates
    PRIMARY KEY (portfolio_id, day)
);

-- migrate:down
-- The reporting views read this table; scripts/apply_db_functions.py recreates them.
DROP VIEW IF EXISTS reporting_portfolio_days;
DROP TABLE IF EXISTS portfolio_days;
