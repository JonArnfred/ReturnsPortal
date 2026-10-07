-- migrate:up
-- Holding episodes derived from the ledger by rebuild_positions() (backend/db/functions/
-- 200_rebuild_positions.sql); rebuilt after every ingest, never hand-edited. A position opens with
-- the first trade that moves a security's quantity away from zero and closes when it returns to
-- zero, so (portfolio, security, opened) identifies it and its id survives rebuilds. Money columns
-- are ledger facts; valuation against the latest broker mark happens in the read model.
CREATE TABLE IF NOT EXISTS positions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    portfolio_id bigint NOT NULL REFERENCES portfolios (id) ON DELETE CASCADE,
    security_id bigint NOT NULL REFERENCES securities (id),
    opened date NOT NULL,
    closed date,
    position_type text NOT NULL CHECK (position_type IN ('long', 'short')),
    currency char(3),                          -- instrument currency
    base_currency char(3) NOT NULL,
    quantity numeric(24, 8) NOT NULL,          -- raw ledger quantity held now; zero when closed
    basis_factor numeric(24, 12) NOT NULL DEFAULT 1,  -- quantity x basis_factor = shares on the price history's basis
    buys integer NOT NULL,
    sells integer NOT NULL,
    shares_bought numeric(24, 8) NOT NULL,     -- on today's split-adjusted basis
    shares_sold numeric(24, 8) NOT NULL,
    avg_buy_price numeric(24, 8),              -- split-adjusted, instrument currency
    avg_sell_price numeric(24, 8),
    buy_cash_local numeric(24, 8) NOT NULL,    -- cash paid for purchases (positive)
    sell_cash_local numeric(24, 8) NOT NULL,   -- cash received from sales
    buy_cash_base numeric(24, 8) NOT NULL,
    sell_cash_base numeric(24, 8) NOT NULL,
    invested_local numeric(24, 8) NOT NULL,    -- purchases plus the costs booked on them
    invested_base numeric(24, 8) NOT NULL,
    dividends_local numeric(24, 8) NOT NULL,   -- dividends net of withholding tax plus lending income
    dividends_base numeric(24, 8) NOT NULL,
    costs_local numeric(24, 8) NOT NULL,       -- commissions, fees and taxes (negative)
    costs_base numeric(24, 8) NOT NULL,
    rebuilt_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (portfolio_id, security_id, opened)
);

CREATE INDEX IF NOT EXISTS positions_security_idx ON positions (security_id);

-- migrate:down
DROP TABLE IF EXISTS positions;
