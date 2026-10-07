-- Reporting projections retain the complete ledger and engine results. The boundary is the
-- beginning of reporting_start_date, so that day's PnL is included.
CREATE OR REPLACE VIEW reporting_portfolio_days AS
WITH unitized AS (
    SELECT d.*, p.reporting_start_date,
           100 * numeric_product(1 + COALESCE(d.daily_return_pct, 0))
               OVER (PARTITION BY d.portfolio_id ORDER BY d.day) AS reporting_unit_price
    FROM portfolio_days d JOIN portfolios p ON p.id = d.portfolio_id
    WHERE p.reporting_start_date IS NULL OR d.day >= p.reporting_start_date
)
SELECT portfolio_id, day, base_currency, nav, positions_value, cash_value, nav_prev, flow,
       daily_pnl, daily_return_pct,
       CASE WHEN reporting_start_date IS NULL THEN unit_price ELSE reporting_unit_price END AS unit_price,
       CASE WHEN reporting_start_date IS NULL THEN units
            WHEN reporting_unit_price > 0 THEN nav / reporting_unit_price ELSE 0 END AS units,
       CASE WHEN reporting_start_date IS NULL THEN cumulative_return_pct
            ELSE reporting_unit_price / 100 - 1 END AS cumulative_return_pct,
       CASE WHEN reporting_start_date IS NULL THEN drawdown_pct
            ELSE reporting_unit_price / GREATEST(100, MAX(reporting_unit_price)
                OVER (PARTITION BY portfolio_id ORDER BY day)) - 1 END AS drawdown_pct,
       broker_value, reporting_start_date
FROM unitized;

CREATE OR REPLACE VIEW reporting_pnl_days AS
SELECT d.portfolio_id, d.position_key, d.day, d.position_kind,
       d.security_id, d.currency, d.base_currency, d.quantity_prev,
       d.quantity, d.trade_quantity, d.basis_factor, d.inferred_split,
       d.price_prev, d.price, d.price_date, d.price_source,
       d.fx_prev, d.fx, d.fx_date, d.execution_price,
       d.execution_fx, d.market_value_local, d.market_value_base, d.prev_market_value_base,
       d.trade_flow_local, d.trade_flow_base, d.flow_base, d.price_effect_base,
       d.price_effect_local, d.fx_effect_base, d.interaction_effect_base, d.dividend_effect_base,
       d.dividend_effect_local, d.interest_effect_base, d.cost_effect_base, d.cost_effect_local,
       d.daily_pnl_base, d.daily_pnl_local, d.daily_return_pct, d.constant_currency_return_pct,
       SUM(d.daily_pnl_base) OVER w AS total_pnl_base,
       SUM(d.daily_pnl_local) OVER w AS total_pnl_local
FROM pnl_days d JOIN portfolios p ON p.id = d.portfolio_id
WHERE p.reporting_start_date IS NULL OR d.day >= p.reporting_start_date
WINDOW w AS (PARTITION BY d.portfolio_id, d.position_key ORDER BY d.day);
