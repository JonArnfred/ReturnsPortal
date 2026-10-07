-- migrate:up
-- Daily FX in the engine's convention: base currency per one unit of the foreign currency,
-- crossed through EUR. One row per published day; the engine forward-fills gaps. The base->base
-- row is always written as 1. Rebuilt from ecb_reference_rates, never hand-edited.
CREATE TABLE IF NOT EXISTS fx_rates (
    rate_date date NOT NULL,
    base_currency char(3) NOT NULL,
    currency char(3) NOT NULL,
    rate numeric(24, 12) NOT NULL,
    source text NOT NULL CHECK (source IN ('ecb', 'identity')),
    PRIMARY KEY (base_currency, currency, rate_date)
);

-- migrate:down
DROP TABLE IF EXISTS fx_rates;
