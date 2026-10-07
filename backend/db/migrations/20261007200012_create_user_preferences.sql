-- migrate:up
-- Small key/value store for UI preferences (saved default filters per page). Single-user app; the
-- key names the page and the preference, e.g. "filters:orders".
CREATE TABLE IF NOT EXISTS user_preferences (
    key text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- migrate:down
DROP TABLE IF EXISTS user_preferences;
