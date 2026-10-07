-- migrate:up
CREATE TABLE IF NOT EXISTS exchanges (
    exchange_id text PRIMARY KEY,
    mic text,
    iso_mic text,
    operating_mic text,
    name text,
    country_code text,
    currency char(3),
    timezone text,
    raw jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- migrate:down
DROP TABLE IF EXISTS exchanges;
