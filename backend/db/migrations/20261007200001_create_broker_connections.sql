-- migrate:up
CREATE TABLE IF NOT EXISTS broker_connections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    broker text NOT NULL CHECK (broker IN ('saxo', 'ibkr')),
    environment text NOT NULL CHECK (environment IN ('live', 'sim')),
    client_key text,
    client_name text,
    base_currency char(3),
    access_token_encrypted text NOT NULL,
    refresh_token_encrypted text,
    access_token_expires_at timestamptz NOT NULL,
    refresh_token_expires_at timestamptz,
    status text NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'expired', 'error')),
    last_sync_started_at timestamptz,
    last_sync_finished_at timestamptz,
    last_sync_error text,
    -- The window of the last successful sync. An ingest reads the latest snapshots (positions, balances)
    -- from it, so a run after a failed sync does not see that sync's partial capture, and the next
    -- sync starts from it.
    last_success_started_at timestamptz,
    last_success_finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    query_id text,                        -- brokers without OAuth (IBKR Flex): the report query id
    UNIQUE (broker, environment)
);

-- migrate:down
DROP TABLE IF EXISTS broker_connections;
