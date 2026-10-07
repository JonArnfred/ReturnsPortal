"""Read-only dashboard queries over the engine's stored results."""

SNAPSHOT = "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"

COVERAGE = """
SELECT p.id AS portfolio_id, COALESCE(p.display_name, p.name) AS portfolio_name,
       p.base_currency, p.reporting_start_date,
       MIN(d.day) AS first_day, MAX(d.day) AS last_day,
       (SELECT COUNT(*) FROM reconciliation_issues i WHERE i.portfolio_id = p.id
        AND (p.reporting_start_date IS NULL OR i.day >= p.reporting_start_date)) AS issues
FROM portfolios p LEFT JOIN reporting_portfolio_days d ON d.portfolio_id = p.id
GROUP BY p.id ORDER BY p.id
"""

# Use observations already incorporated in the rebuild, not newly fetched raw prices.
# A fresh but unchanged close is valid; nonzero PnL is not a freshness test. Synthetic
# cash prices and base-currency identity FX must not make carried days look fresh.
# Today qualifies once it has an observation; its closes are intraday until the markets close.
VALUATION_DAY = """
WITH activity AS (
    SELECT day,
           BOOL_OR(position_kind = 'security' OR currency <> base_currency) AS needs_market_data,
           BOOL_OR((position_kind = 'security' AND price_source = 'close' AND price_date = day)
                   OR (currency <> base_currency AND fx_date = day)
                   OR trade_quantity <> 0 OR flow_base <> 0
                   OR dividend_effect_base <> 0 OR interest_effect_base <> 0
                   OR cost_effect_base <> 0) AS has_observation_or_activity
    FROM reporting_pnl_days
    WHERE day <= %(day)s
      AND (quantity <> 0 OR quantity_prev <> 0 OR trade_quantity <> 0 OR flow_base <> 0
           OR daily_pnl_base <> 0)
    GROUP BY day
)
SELECT d.day, d.day >= CURRENT_DATE AS intraday
FROM reporting_portfolio_days d LEFT JOIN activity a ON a.day = d.day
WHERE d.day <= %(day)s
GROUP BY d.day
HAVING COUNT(*) = %(portfolio_count)s
   AND (BOOL_OR(d.flow <> 0)
        OR BOOL_OR(COALESCE(a.has_observation_or_activity, FALSE))
        OR NOT BOOL_OR(COALESCE(a.needs_market_data, FALSE)))
ORDER BY d.day DESC LIMIT 1
"""

PORTFOLIOS = """
SELECT portfolio_id, nav, daily_pnl, daily_return_pct, cumulative_return_pct
FROM reporting_portfolio_days WHERE day = %(day)s
"""

SERIES = """
SELECT day, SUM(nav) AS nav FROM reporting_portfolio_days
WHERE day <= %(day)s GROUP BY day ORDER BY day
"""

TOTAL = """
SELECT SUM(nav) AS nav, SUM(daily_pnl) AS daily_pnl,
       CASE WHEN SUM(nav_prev) > 0 THEN SUM(daily_pnl) / SUM(nav_prev) END AS daily_return_pct
FROM reporting_portfolio_days WHERE day = %(day)s
"""

FX = """
SELECT currency, SUM(fx_effect_base) AS effect
FROM reporting_pnl_days WHERE day = %(day)s GROUP BY currency ORDER BY effect DESC, currency
"""

# Rank in SQL over the entire day, without the public PnL endpoint's pagination cap.
CONTRIBUTORS = """
WHERE d.day = %(day)s AND (d.quantity <> 0 OR d.quantity_prev <> 0 OR d.daily_pnl_base <> 0)
ORDER BY d.daily_pnl_base {direction}, d.portfolio_id, d.position_key LIMIT 5
"""
