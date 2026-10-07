-- migrate:up
CREATE TABLE IF NOT EXISTS portfolios (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id bigint REFERENCES broker_connections (id) ON DELETE SET NULL,
    name text NOT NULL,
    base_currency char(3) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    display_name text,                    -- user-chosen name; NULL falls back to the broker-provided name
    reporting_start_date date,            -- reports start here; earlier history still feeds the engine
    UNIQUE (connection_id)
);

-- migrate:down
-- The reporting views read this table; scripts/apply_db_functions.py recreates them.
DROP VIEW IF EXISTS reporting_portfolio_days;
DROP VIEW IF EXISTS reporting_pnl_days;
DROP TABLE IF EXISTS portfolios;
