-- migrate:up
-- Derived tables written by the SQL PnL engine (backend/db/functions/*.sql). Rebuilt per portfolio
-- from the ledger, daily_prices and fx_rates; never hand-edited.

-- One row per position per calendar day: securities and cash balances per currency alike
-- (documentation/VISION.md 4.2 and 4.4). Rows exist from the position's first ledger day while it
-- is held or has an event that day.
CREATE TABLE IF NOT EXISTS pnl_days (
    portfolio_id bigint NOT NULL REFERENCES portfolios (id) ON DELETE CASCADE,
    position_key text NOT NULL,          -- 'sec:<security_id>' or 'cash:<currency>'
    day date NOT NULL,
    position_kind text NOT NULL CHECK (position_kind IN ('security', 'cash')),
    security_id bigint REFERENCES securities (id),
    currency char(3) NOT NULL,           -- instrument currency, or the cash currency
    base_currency char(3) NOT NULL,
    quantity_prev numeric(28, 10) NOT NULL,   -- on the split-adjusted basis of the price history
    quantity numeric(28, 10) NOT NULL,
    trade_quantity numeric(28, 10) NOT NULL,
    basis_factor numeric(24, 12) NOT NULL,    -- raw ledger quantity x basis_factor = quantity
    inferred_split numeric(24, 12) NOT NULL,  -- part of basis_factor inferred from trade prices vs closes
    price_prev numeric(24, 10),
    price numeric(24, 10),
    price_date date,                     -- observation date of the carried price
    price_source text,                   -- close, ledger, or NULL when no price is known
    fx_prev numeric(24, 12),
    fx numeric(24, 12),
    fx_date date,
    execution_price numeric(24, 10),
    execution_fx numeric(24, 12),
    market_value_local numeric(24, 8) NOT NULL,
    market_value_base numeric(24, 8) NOT NULL,
    prev_market_value_base numeric(24, 8) NOT NULL,
    trade_flow_local numeric(24, 8) NOT NULL,
    trade_flow_base numeric(24, 8) NOT NULL,
    flow_base numeric(24, 8) NOT NULL,   -- all base money into the position: trades minus income and costs
    price_effect_base numeric(24, 8) NOT NULL,
    price_effect_local numeric(24, 8) NOT NULL,
    fx_effect_base numeric(24, 8) NOT NULL,
    interaction_effect_base numeric(24, 8) NOT NULL,
    dividend_effect_base numeric(24, 8) NOT NULL,
    dividend_effect_local numeric(24, 8) NOT NULL,
    interest_effect_base numeric(24, 8) NOT NULL,
    cost_effect_base numeric(24, 8) NOT NULL,
    cost_effect_local numeric(24, 8) NOT NULL,
    daily_pnl_base numeric(24, 8) NOT NULL,
    daily_pnl_local numeric(24, 8) NOT NULL,
    daily_return_pct numeric(20, 12),
    constant_currency_return_pct numeric(20, 12),
    total_pnl_base numeric(24, 8) NOT NULL,
    total_pnl_local numeric(24, 8) NOT NULL,
    PRIMARY KEY (portfolio_id, position_key, day)
);

CREATE INDEX IF NOT EXISTS pnl_days_portfolio_day_idx ON pnl_days (portfolio_id, day);
CREATE INDEX IF NOT EXISTS pnl_days_security_idx ON pnl_days (security_id, day);

-- migrate:down
-- The reporting views read this table; scripts/apply_db_functions.py recreates them.
DROP VIEW IF EXISTS reporting_pnl_days;
DROP TABLE IF EXISTS pnl_days;
