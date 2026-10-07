-- migrate:up
-- Every broker response is kept verbatim so mappings can be replayed without re-pulling.
CREATE TABLE IF NOT EXISTS broker_raw_payloads (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    connection_id bigint NOT NULL REFERENCES broker_connections (id) ON DELETE CASCADE,
    endpoint text NOT NULL,
    params jsonb NOT NULL DEFAULT '{}'::jsonb,
    fetched_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status_code integer NOT NULL,
    payload jsonb
);

CREATE INDEX IF NOT EXISTS broker_raw_payloads_connection_endpoint_idx
    ON broker_raw_payloads (connection_id, endpoint, fetched_at);

-- migrate:down
DROP TABLE IF EXISTS broker_raw_payloads;
