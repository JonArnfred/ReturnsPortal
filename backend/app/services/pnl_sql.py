"""SQL over the derived PnL tables (pnl_days, portfolio_days, reconciliation_issues)."""

from __future__ import annotations

REBUILD_PORTFOLIO = "SELECT * FROM rebuild_pnl(%(portfolio_id)s, %(through)s)"

SELECT_PORTFOLIO_IDS = "SELECT id FROM portfolios ORDER BY id"

PNL_ROWS_BASE = """
FROM reporting_pnl_days d
JOIN portfolios p ON p.id = d.portfolio_id
LEFT JOIN securities s ON s.id = d.security_id
"""

PNL_ROWS_COLUMNS = """
SELECT d.day, d.portfolio_id, COALESCE(p.display_name, p.name) AS portfolio_name,
       d.position_kind, d.position_key, d.security_id,
       CASE WHEN d.position_kind = 'cash' THEN 'Cash ' || d.currency ELSE COALESCE(s.name, s.ticker) END
           AS security_name,
       CASE WHEN d.position_kind = 'cash' THEN d.currency
            WHEN s.mic IS NOT NULL THEN s.ticker || ':' || s.mic ELSE s.ticker END AS full_ticker,
       d.currency, d.base_currency,
       CASE WHEN d.quantity < 0 OR (d.quantity = 0 AND d.quantity_prev < 0) THEN 'short' ELSE 'long' END
           AS position_type,
       d.quantity, d.quantity_prev, d.trade_quantity, d.basis_factor,
       d.price, d.price - d.price_prev AS price_change, d.price_date, d.price_source,
       d.fx, d.fx - d.fx_prev AS fx_change, d.execution_price, d.execution_fx,
       d.market_value_base, d.market_value_local, d.prev_market_value_base,
       d.trade_flow_base, d.trade_flow_local, d.flow_base,
       d.price_effect_base, d.price_effect_local, d.fx_effect_base, d.interaction_effect_base,
       d.dividend_effect_base, d.dividend_effect_local, d.interest_effect_base,
       d.cost_effect_base, d.cost_effect_local,
       d.daily_pnl_base, d.daily_pnl_local, d.daily_return_pct, d.constant_currency_return_pct,
       d.total_pnl_base, d.total_pnl_local
"""

SELECT_PORTFOLIO_DAYS = """
WITH contributions AS (
    SELECT portfolio_id, day,
           SUM(flow) OVER (PARTITION BY portfolio_id ORDER BY day) AS cumulative_cash_additions
    FROM portfolio_days
    WHERE portfolio_id = %(portfolio_id)s
)
SELECT d.day, d.portfolio_id, COALESCE(p.display_name, p.name) AS portfolio_name, d.base_currency,
       d.nav, d.positions_value, d.cash_value, d.nav_prev, d.flow, d.daily_pnl, d.daily_return_pct,
       d.unit_price, d.units, d.cumulative_return_pct, d.drawdown_pct, d.broker_value, p.reporting_start_date,
       c.cumulative_cash_additions, d.nav - c.cumulative_cash_additions AS returns_base
FROM reporting_portfolio_days d
JOIN portfolios p ON p.id = d.portfolio_id
JOIN contributions c ON c.portfolio_id = d.portfolio_id AND c.day = d.day
WHERE d.portfolio_id = %(portfolio_id)s
  AND (%(date_gte)s::date IS NULL OR d.day >= %(date_gte)s)
  AND (%(date_lte)s::date IS NULL OR d.day <= %(date_lte)s)
ORDER BY d.day
"""

# Portfolios join on their reporting dates with opening NAV as a start-of-day contribution.
# Stop at the latest shared day so a stale portfolio cannot disappear and create a false loss.
SELECT_TOTAL_DAYS = """
WITH coverage AS (
    SELECT portfolio_id, MIN(day) AS first_day, MAX(day) AS last_day
    FROM reporting_portfolio_days GROUP BY portfolio_id
), boundary AS (
    SELECT MIN(last_day) AS last_day FROM coverage HAVING MAX(first_day) <= MIN(last_day)
), contributions AS (
    -- Lifetime booked deposits minus withdrawals, before any reporting/date filters.
    -- Synthetic opening NAV used for unitization is not a cash addition.
    SELECT portfolio_id, day,
           SUM(flow) OVER (PARTITION BY portfolio_id ORDER BY day) AS cumulative_cash_additions
    FROM portfolio_days
), included AS (
    SELECT d.*, c.cumulative_cash_additions,
           ROW_NUMBER() OVER (PARTITION BY d.portfolio_id ORDER BY d.day) AS rn
    FROM reporting_portfolio_days d
    JOIN contributions c ON c.portfolio_id = d.portfolio_id AND c.day = d.day
    WHERE d.day <= (SELECT last_day FROM boundary)
),
daily AS (
    SELECT d.day, MAX(d.base_currency) AS base_currency,
           SUM(d.nav) AS nav, SUM(d.positions_value) AS positions_value, SUM(d.cash_value) AS cash_value,
           SUM(d.cumulative_cash_additions) AS cumulative_cash_additions,
           SUM(d.nav_prev) AS opening_nav, SUM(d.flow) AS booked_flow, SUM(d.daily_pnl) AS daily_pnl,
           SUM(CASE WHEN d.rn = 1 THEN d.nav_prev ELSE 0 END) AS entering_nav,
           CASE WHEN COUNT(d.broker_value) = COUNT(*) THEN SUM(d.broker_value) END AS broker_value
    FROM included d
    -- Different currencies cannot be summed without a group base-currency conversion.
    WHERE (SELECT COUNT(DISTINCT base_currency) FROM included) = 1
    GROUP BY d.day
),
series AS (
    SELECT x.*, COALESCE(LAG(x.nav) OVER (ORDER BY x.day), x.opening_nav) AS nav_prev,
           x.booked_flow + CASE WHEN ROW_NUMBER() OVER (ORDER BY x.day) > 1
                               THEN x.entering_nav ELSE 0 END AS flow,
           CASE WHEN x.opening_nav > 0 THEN x.daily_pnl / x.opening_nav END AS daily_return_pct
    FROM daily x
),
unitized AS (
    SELECT s.*, 100 * numeric_product(1 + COALESCE(s.daily_return_pct, 0)) OVER (ORDER BY s.day) AS unit_price
    FROM series s
),
reported AS (
    SELECT u.day, 0 AS portfolio_id, 'Total' AS portfolio_name, u.base_currency,
           u.nav, u.positions_value, u.cash_value, u.nav_prev, u.flow, u.daily_pnl, u.daily_return_pct,
           u.unit_price, CASE WHEN u.unit_price > 0 THEN u.nav / u.unit_price ELSE 0 END AS units,
           u.unit_price / 100 - 1 AS cumulative_return_pct,
           u.unit_price / GREATEST(100, MAX(u.unit_price) OVER (ORDER BY u.day)) - 1 AS drawdown_pct,
           u.broker_value, NULL::date AS reporting_start_date,
           u.cumulative_cash_additions, u.nav - u.cumulative_cash_additions AS returns_base
    FROM unitized u
)
SELECT * FROM reported
WHERE (%(date_gte)s::date IS NULL OR day >= %(date_gte)s)
  AND (%(date_lte)s::date IS NULL OR day <= %(date_lte)s)
ORDER BY day
"""

SELECT_ISSUES = """
SELECT i.id, i.portfolio_id, COALESCE(p.display_name, p.name) AS portfolio_name, i.day, i.kind,
       i.security_id, s.name AS security_name,
       CASE WHEN s.id IS NULL THEN NULL WHEN s.mic IS NOT NULL THEN s.ticker || ':' || s.mic ELSE s.ticker END
           AS full_ticker,
       i.currency, i.amount, i.message, i.created_at,
       c.broker, d.gap_fx, d.gap_cash, d.gap_securities
FROM reconciliation_issues i
JOIN portfolios p ON p.id = i.portfolio_id
LEFT JOIN broker_connections c ON c.id = p.connection_id
LEFT JOIN securities s ON s.id = i.security_id
LEFT JOIN portfolio_days d ON i.kind = 'nav_mismatch' AND d.portfolio_id = i.portfolio_id AND d.day = i.day
WHERE p.reporting_start_date IS NULL OR i.day >= p.reporting_start_date
ORDER BY i.day DESC, i.kind, i.id
"""

# Per currency held on a NAV-mismatch day: the ECB rate the engine valued it at, the broker's own
# rate (broker_fx_rate_on, the same lookup rebuild_pnl uses), and what the difference contributes
# to gap_fx. The contributions of one issue sum to its portfolio_days.gap_fx.
SELECT_ISSUE_FX_RATES = """
SELECT i.id AS issue_id, d.currency,
       MAX(d.fx) AS ecb_rate, MAX(d.fx_date) AS ecb_rate_date,
       r.rate AS broker_rate, r.rate_date AS broker_rate_date,
       r.quote_currency AS broker_quote_currency, r.quote_rate AS broker_quote_rate,
       SUM(d.market_value_local) AS value_local,
       SUM(d.market_value_local * (d.fx - r.rate)) AS gap_fx
FROM reconciliation_issues i
JOIN portfolios p ON p.id = i.portfolio_id
JOIN pnl_days d ON d.portfolio_id = i.portfolio_id AND d.day = i.day AND d.market_value_local <> 0
LEFT JOIN LATERAL broker_fx_rate_on(i.portfolio_id, d.currency, d.day) r ON TRUE
WHERE i.kind = 'nav_mismatch' AND (p.reporting_start_date IS NULL OR i.day >= p.reporting_start_date)
GROUP BY i.id, d.currency, r.rate, r.rate_date, r.quote_currency, r.quote_rate
ORDER BY i.id, ABS(SUM(d.market_value_local * (d.fx - r.rate))) DESC NULLS LAST, d.currency
"""

SELECT_ENGINE_STATUS = """
SELECT p.id AS portfolio_id, COALESCE(p.display_name, p.name) AS portfolio_name,
       (SELECT MIN(day) FROM reporting_portfolio_days d WHERE d.portfolio_id = p.id) AS first_day,
       (SELECT MAX(day) FROM reporting_portfolio_days d WHERE d.portfolio_id = p.id) AS last_day,
       (SELECT COUNT(*) FROM reporting_pnl_days d WHERE d.portfolio_id = p.id) AS position_rows,
       (SELECT COUNT(*) FROM reconciliation_issues i WHERE i.portfolio_id = p.id
        AND (p.reporting_start_date IS NULL OR i.day >= p.reporting_start_date)) AS issues
FROM portfolios p ORDER BY p.id
"""


# Paged attribution rows: PNL_ROWS_COLUMNS + PNL_ROWS_BASE + WHERE (these filters, joined with AND)
# + PNL_ROWS_PAGE. Sort keys map to expressions so ORDER BY never takes user text.
COUNT_TOTAL = "SELECT COUNT(*) AS total "
PNL_FILTERS = {
    "portfolio_id": "d.portfolio_id = %(portfolio_id)s",
    "security_id": "d.security_id = %(security_id)s",
    "position_kind": "d.position_kind = %(position_kind)s",
    "long": "(d.quantity > 0 OR (d.quantity = 0 AND d.quantity_prev > 0))",
    "short": "(d.quantity < 0 OR (d.quantity = 0 AND d.quantity_prev < 0))",
    "date_gte": "d.day >= %(date_gte)s",
    "date_lte": "d.day <= %(date_lte)s",
    "search": (
        "(s.name ILIKE %(search)s OR s.ticker ILIKE %(search)s OR d.currency ILIKE %(search)s"
        " OR (s.ticker || ':' || COALESCE(s.mic, '')) ILIKE %(search)s)"
    ),
    "active_only": "(d.quantity <> 0 OR d.quantity_prev <> 0 OR d.daily_pnl_base <> 0)",
}
PNL_ORDER_COLUMNS = {
    "day": "d.day",
    "portfolio_name": "COALESCE(p.display_name, p.name)",
    "security_name": (
        "CASE WHEN d.position_kind = 'cash' THEN 'Cash ' || d.currency ELSE COALESCE(s.name, s.ticker) END"
    ),
    "quantity": "d.quantity",
    "market_value_base": "d.market_value_base",
    "price_effect_base": "d.price_effect_base",
    "trade_flow_base": "d.trade_flow_base",
    "fx_effect_base": "d.fx_effect_base",
    "interaction_effect_base": "d.interaction_effect_base",
    "dividend_effect_base": "d.dividend_effect_base",
    "interest_effect_base": "d.interest_effect_base",
    "cost_effect_base": "d.cost_effect_base",
    "daily_pnl_base": "d.daily_pnl_base",
    "daily_return_pct": "d.daily_return_pct",
    "constant_currency_return_pct": "d.constant_currency_return_pct",
    "total_pnl_base": "d.total_pnl_base",
}
PNL_ROWS_PAGE = (
    " ORDER BY {} {} NULLS LAST, d.day DESC, ABS(d.market_value_base) DESC, d.position_key"
    " OFFSET %(offset)s LIMIT %(limit)s"
)
