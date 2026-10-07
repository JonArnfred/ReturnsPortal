-- migrate:up
-- ECB euro reference rates as published: units of the currency per one euro, working days only.
-- Kept verbatim so the crosses below can be rebuilt for any base currency without re-fetching.
CREATE TABLE IF NOT EXISTS ecb_reference_rates (
    rate_date date NOT NULL,
    currency char(3) NOT NULL,
    units_per_eur numeric(24, 10) NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (rate_date, currency)
);

-- migrate:down
DROP TABLE IF EXISTS ecb_reference_rates;
