-- migrate:up
-- Broker orders, working and historical, rebuilt from raw payloads on every ingest (upsert on the
-- broker's order id). ``status`` is normalized (working, filled, cancelled, expired, rejected, other);
-- ``broker_status`` keeps the broker's own word. ``is_open`` means the order was in the broker's
-- working-orders list at the latest sync.
CREATE TABLE IF NOT EXISTS orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id bigint NOT NULL REFERENCES broker_connections (id) ON DELETE CASCADE,
    portfolio_id bigint NOT NULL REFERENCES portfolios (id),
    broker_order_id text NOT NULL,
    account_key text,
    security_id bigint REFERENCES securities (id),
    instrument_symbol text,
    instrument_name text,
    status text NOT NULL CHECK (status IN ('working', 'filled', 'cancelled', 'expired', 'rejected', 'other')),
    broker_status text,
    is_open boolean NOT NULL DEFAULT false,
    buy_sell text CHECK (buy_sell IN ('buy', 'sell')),
    order_type text,
    duration text,
    quantity numeric(24, 8),
    filled_quantity numeric(24, 8),
    price numeric(24, 8),
    average_fill_price numeric(24, 8),
    currency char(3),
    placed_at timestamptz,
    last_activity_at timestamptz,
    expires_at timestamptz,
    order_relation text,
    source_endpoint text NOT NULL,
    raw jsonb NOT NULL,
    fetched_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (connection_id, broker_order_id)
);

CREATE INDEX IF NOT EXISTS orders_portfolio_placed_idx ON orders (portfolio_id, placed_at DESC);

-- migrate:down
DROP TABLE IF EXISTS orders;
