-- migrate:up
-- Derived tables written by the SQL PnL engine (backend/db/functions/*.sql). Rebuilt per portfolio
-- from the ledger, daily_prices and fx_rates; never hand-edited.

-- Data-quality and reconciliation findings of a rebuild (documentation/VISION.md 4.5 and 6).
CREATE TABLE IF NOT EXISTS reconciliation_issues (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    portfolio_id bigint NOT NULL REFERENCES portfolios (id) ON DELETE CASCADE,
    day date NOT NULL,
    kind text NOT NULL,                   -- missing_price, stale_price, missing_fx, nav_mismatch, ...
    security_id bigint REFERENCES securities (id),
    currency char(3),
    amount numeric(24, 8),
    message text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS reconciliation_issues_portfolio_day_idx ON reconciliation_issues (portfolio_id, day);

-- migrate:down
DROP TABLE IF EXISTS reconciliation_issues;
