-- migrate:up
-- Append-only source of truth. One row per broker booking or trade, idempotent on broker_ref.
CREATE TABLE IF NOT EXISTS ledger_transactions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id bigint NOT NULL REFERENCES broker_connections (id) ON DELETE CASCADE,
    portfolio_id bigint NOT NULL REFERENCES portfolios (id),
    account_key text,
    broker_ref text NOT NULL,
    kind text NOT NULL CHECK (kind IN (
        'trade', 'corporate_action', 'deposit', 'withdrawal', 'transfer', 'dividend', 'withholding_tax',
        'commission', 'fee', 'tax', 'interest', 'lending_income', 'other'
    )),
    trade_date date NOT NULL,
    value_date date,
    security_id bigint REFERENCES securities (id),
    quantity numeric(24, 8),
    price numeric(24, 8),
    currency char(3) NOT NULL,
    amount_local numeric(24, 8) NOT NULL,
    account_currency char(3),
    amount_account numeric(24, 8),
    base_currency char(3) NOT NULL,
    amount_base numeric(24, 8),
    fx_rate_base numeric(24, 12),
    related_ref text,
    description text,
    source_endpoint text NOT NULL,
    raw jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (connection_id, broker_ref)
);

CREATE INDEX IF NOT EXISTS ledger_transactions_portfolio_date_idx ON ledger_transactions (portfolio_id, trade_date);
CREATE INDEX IF NOT EXISTS ledger_transactions_security_idx ON ledger_transactions (security_id, trade_date);

-- migrate:down
DROP TABLE IF EXISTS ledger_transactions;
