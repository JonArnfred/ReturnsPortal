-- migrate:up
-- Application settings changed from the UI (Setup), as opposed to UI preferences. A missing row means
-- the default from the environment applies (e.g. REPORTING_CURRENCY).
CREATE TABLE IF NOT EXISTS app_settings (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- migrate:down
DROP TABLE IF EXISTS app_settings;
