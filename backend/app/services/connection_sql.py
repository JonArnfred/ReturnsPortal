"""SQL for broker connections, accounts, raw payload capture, and OAuth state."""

from __future__ import annotations

INSERT_OAUTH_STATE = """
INSERT INTO oauth_states (state, broker) VALUES (%(state)s, %(broker)s)
"""

CONSUME_OAUTH_STATE = """
DELETE FROM oauth_states
WHERE state = %(state)s AND created_at > CURRENT_TIMESTAMP - INTERVAL '15 minutes'
RETURNING state, broker
"""

PURGE_OAUTH_STATES = """
DELETE FROM oauth_states WHERE created_at < CURRENT_TIMESTAMP - INTERVAL '1 day'
"""

UPSERT_CONNECTION = """
INSERT INTO broker_connections (
    broker, environment, access_token_encrypted, refresh_token_encrypted,
    access_token_expires_at, refresh_token_expires_at, query_id, status
) VALUES (
    %(broker)s, %(environment)s, %(access_token_encrypted)s, %(refresh_token_encrypted)s,
    %(access_token_expires_at)s, %(refresh_token_expires_at)s, %(query_id)s, 'connected'
)
ON CONFLICT (broker, environment) DO UPDATE SET
    access_token_encrypted = EXCLUDED.access_token_encrypted,
    refresh_token_encrypted = EXCLUDED.refresh_token_encrypted,
    access_token_expires_at = EXCLUDED.access_token_expires_at,
    refresh_token_expires_at = EXCLUDED.refresh_token_expires_at,
    query_id = EXCLUDED.query_id,
    status = 'connected',
    last_sync_error = NULL,
    updated_at = CURRENT_TIMESTAMP
RETURNING id
"""

STORE_TOKENS = """
UPDATE broker_connections SET
    access_token_encrypted = %(access_token_encrypted)s,
    refresh_token_encrypted = COALESCE(%(refresh_token_encrypted)s, refresh_token_encrypted),
    access_token_expires_at = %(access_token_expires_at)s,
    refresh_token_expires_at = COALESCE(%(refresh_token_expires_at)s, refresh_token_expires_at),
    status = 'connected',
    updated_at = CURRENT_TIMESTAMP
WHERE id = %(id)s
"""

UPDATE_CLIENT_DETAILS = """
UPDATE broker_connections SET
    client_key = %(client_key)s,
    client_name = %(client_name)s,
    base_currency = %(base_currency)s,
    updated_at = CURRENT_TIMESTAMP
WHERE id = %(id)s
"""

MARK_SYNC_STARTED = """
UPDATE broker_connections SET last_sync_started_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
WHERE id = %(id)s
"""

MARK_TOKEN_EXPIRED = """
UPDATE broker_connections SET status = 'expired', last_sync_error = %(error)s, updated_at = CURRENT_TIMESTAMP
WHERE id = %(id)s
"""

MARK_SYNC_FINISHED = """
UPDATE broker_connections SET
    last_sync_finished_at = CURRENT_TIMESTAMP,
    last_sync_error = %(error)s,
    last_success_started_at = CASE WHEN %(error)s::text IS NULL THEN last_sync_started_at
                                   ELSE last_success_started_at END,
    last_success_finished_at = CASE WHEN %(error)s::text IS NULL THEN CURRENT_TIMESTAMP
                                    ELSE last_success_finished_at END,
    -- A rejected token stays expired (MARK_TOKEN_EXPIRED) until the broker is authorized again.
    status = CASE WHEN %(error)s::text IS NULL THEN 'connected'
                  WHEN status = 'expired' THEN 'expired'
                  ELSE 'error' END,
    updated_at = CURRENT_TIMESTAMP
WHERE id = %(id)s
"""

SELECT_CONNECTION_SECRETS = """
SELECT id, broker, environment, client_key, access_token_encrypted, refresh_token_encrypted,
       access_token_expires_at, refresh_token_expires_at, query_id
FROM broker_connections WHERE id = %(id)s
"""

SELECT_CONNECTIONS = """
SELECT c.id, c.broker, c.environment, c.client_key, c.client_name, c.base_currency, c.status, c.query_id,
       c.access_token_expires_at, c.refresh_token_expires_at,
       c.last_sync_started_at, c.last_sync_finished_at, c.last_sync_error, c.last_success_finished_at, c.created_at,
       COALESCE(a.account_count, 0) AS account_count
FROM broker_connections c
LEFT JOIN (
    SELECT connection_id, COUNT(*) AS account_count FROM broker_accounts WHERE active GROUP BY connection_id
) a ON a.connection_id = c.id
ORDER BY c.broker, c.environment
"""

INSERT_RAW_PAYLOAD = """
INSERT INTO broker_raw_payloads (connection_id, endpoint, params, status_code, payload)
VALUES (%(connection_id)s, %(endpoint)s, %(params)s, %(status_code)s, %(payload)s)
"""

SELECT_CONNECTION = SELECT_CONNECTIONS.replace("ORDER BY c.broker, c.environment", "WHERE c.id = %(id)s")

SELECT_ACCOUNTS = """
SELECT account_key, account_id, currency, account_type, active, raw
FROM broker_accounts WHERE connection_id = %(connection_id)s ORDER BY account_key
"""

SELECT_RAW_PAYLOADS = """
SELECT id, endpoint, params, fetched_at, status_code, payload
FROM broker_raw_payloads
WHERE connection_id = %(connection_id)s AND endpoint LIKE %(endpoint_prefix)s AND status_code BETWEEN 200 AND 299
  AND (
    NOT %(latest_run_only)s
    -- The last successful run; before one is recorded (or mid-sync), the most recent run.
    OR EXISTS (
        SELECT 1 FROM broker_connections c
        WHERE c.id = %(connection_id)s
          AND CASE WHEN c.last_success_started_at IS NOT NULL
                   THEN fetched_at BETWEEN c.last_success_started_at AND c.last_success_finished_at
                   ELSE fetched_at >= COALESCE(c.last_sync_started_at, '-infinity'::timestamptz)
              END
    )
  )
ORDER BY id
"""
