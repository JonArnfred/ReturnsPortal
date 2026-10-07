-- migrate:up
-- Where each security's prices come from and how far they reach; one row per security once tried.
CREATE TABLE IF NOT EXISTS security_price_sources (
    security_id bigint PRIMARY KEY REFERENCES securities (id) ON DELETE CASCADE,
    source text NOT NULL CHECK (source IN ('saxo', 'yahoo', 'none')),
    yahoo_symbol text,
    first_needed date,
    first_price_date date,
    last_price_date date,
    bars integer NOT NULL DEFAULT 0,
    last_fetched_at timestamptz,
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- migrate:down
DROP TABLE IF EXISTS security_price_sources;
