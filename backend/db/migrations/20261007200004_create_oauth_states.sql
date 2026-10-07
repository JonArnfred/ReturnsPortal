-- migrate:up
CREATE TABLE IF NOT EXISTS oauth_states (
    state text PRIMARY KEY,
    broker text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- migrate:down
DROP TABLE IF EXISTS oauth_states;
