-- migrate:up
CREATE TABLE IF NOT EXISTS position_snapshots (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id bigint NOT NULL REFERENCES broker_connections (id) ON DELETE CASCADE,
    portfolio_id bigint NOT NULL REFERENCES portfolios (id),
    snapshot_date date NOT NULL,
    account_key text,
    broker_position_id text NOT NULL,
    security_id bigint NOT NULL REFERENCES securities (id),
    quantity numeric(24, 8) NOT NULL,
    open_price numeric(24, 8),
    current_price numeric(24, 8),
    currency char(3),
    market_value_local numeric(24, 8),
    market_value_base numeric(24, 8),
    fx_rate_base numeric(24, 12),
    raw jsonb NOT NULL,
    fetched_at timestamptz NOT NULL,
    UNIQUE (connection_id, snapshot_date, broker_position_id)
);

-- migrate:down
DROP TABLE IF EXISTS position_snapshots;
