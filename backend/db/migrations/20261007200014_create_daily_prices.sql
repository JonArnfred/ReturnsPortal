-- migrate:up
-- Daily OHLCV per security, split-adjusted as the source delivers it, in the instrument currency
-- (GBX/ZAc are normalised to GBP/ZAR on ingest). Rebuilt by the price sync; never hand-edited.
CREATE TABLE IF NOT EXISTS daily_prices (
    security_id bigint NOT NULL REFERENCES securities (id) ON DELETE CASCADE,
    price_date date NOT NULL,
    open numeric(24, 8),
    high numeric(24, 8),
    low numeric(24, 8),
    close numeric(24, 8) NOT NULL,
    volume numeric(24, 4),
    currency char(3),
    source text NOT NULL CHECK (source IN ('saxo', 'yahoo', 'ibkr')),  -- ibkr: the broker's own daily mark
    fetched_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (security_id, price_date)
);

-- migrate:down
DROP TABLE IF EXISTS daily_prices;
