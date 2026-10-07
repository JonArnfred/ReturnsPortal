-- The broker's own FX rate for a portfolio's currency on a day: the last stored rate on or before it
-- (carried forward over days without one, like every rate in the engine). Shared by rebuild_pnl's
-- NAV-gap split and the reconciliation read model, so the two always use the same rate.
CREATE OR REPLACE FUNCTION broker_fx_rate_on(p_portfolio_id bigint, p_currency char(3), p_day date)
RETURNS TABLE (rate numeric, rate_date date, quote_currency char(3), quote_rate numeric)
LANGUAGE sql STABLE AS $$
    SELECT x.rate, x.rate_date, x.quote_currency, x.quote_rate
    FROM broker_fx_rates x
    WHERE x.portfolio_id = p_portfolio_id AND x.currency = p_currency AND x.rate_date <= p_day
    ORDER BY x.rate_date DESC
    LIMIT 1
$$;
