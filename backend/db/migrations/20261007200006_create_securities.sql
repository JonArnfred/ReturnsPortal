-- migrate:up
CREATE TABLE IF NOT EXISTS securities (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    broker text NOT NULL,
    uic bigint NOT NULL,
    asset_type text NOT NULL,
    symbol text NOT NULL,
    ticker text NOT NULL,
    mic text,
    name text,
    currency char(3),
    exchange_id text,
    isin text,
    raw jsonb,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (broker, uic, asset_type)
);

CREATE INDEX IF NOT EXISTS securities_ticker_mic_idx ON securities (ticker, mic);

-- migrate:down
DROP TABLE IF EXISTS securities;
