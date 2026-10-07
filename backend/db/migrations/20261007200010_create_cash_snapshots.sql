-- migrate:up
CREATE TABLE IF NOT EXISTS cash_snapshots (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id bigint NOT NULL REFERENCES broker_connections (id) ON DELETE CASCADE,
    portfolio_id bigint NOT NULL REFERENCES portfolios (id),
    snapshot_date date NOT NULL,
    account_key text NOT NULL DEFAULT '',
    currency char(3) NOT NULL,
    cash_balance numeric(24, 8) NOT NULL,
    total_value numeric(24, 8),
    raw jsonb NOT NULL,
    fetched_at timestamptz NOT NULL,
    UNIQUE (connection_id, snapshot_date, account_key, currency)
);

-- migrate:down
DROP TABLE IF EXISTS cash_snapshots;
