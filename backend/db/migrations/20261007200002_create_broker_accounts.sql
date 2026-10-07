-- migrate:up
CREATE TABLE IF NOT EXISTS broker_accounts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id bigint NOT NULL REFERENCES broker_connections (id) ON DELETE CASCADE,
    account_key text NOT NULL,
    account_id text,
    currency char(3),
    account_type text,
    active boolean NOT NULL DEFAULT true,
    raw jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (connection_id, account_key)
);

-- migrate:down
DROP TABLE IF EXISTS broker_accounts;
