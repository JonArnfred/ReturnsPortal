"""SQL for ECB reference rates and the crossed daily FX table."""

from __future__ import annotations

SELECT_ECB_COVERAGE = """
SELECT MIN(rate_date) AS first_date, MAX(rate_date) AS last_date, COUNT(*) AS rows FROM ecb_reference_rates
"""

SELECT_ECB_RATES_SINCE = """
SELECT rate_date, currency, units_per_eur FROM ecb_reference_rates
WHERE %(since)s::date IS NULL OR rate_date >= %(since)s
ORDER BY rate_date, currency
"""

SELECT_BASE_CURRENCIES = """
SELECT DISTINCT base_currency FROM portfolios
"""

SELECT_CROSSED_BASE_CURRENCIES = """
SELECT DISTINCT base_currency FROM fx_rates
"""

DELETE_FX_RATES_SINCE = """
DELETE FROM fx_rates WHERE base_currency = %(base_currency)s AND (%(since)s::date IS NULL OR rate_date >= %(since)s)
"""

SELECT_FX_STATUS = """
WITH needed AS (
    SELECT DISTINCT p.base_currency, x.currency
    FROM portfolios p
    JOIN LATERAL (
        SELECT s.currency FROM securities s JOIN ledger_transactions t ON t.security_id = s.id
        WHERE t.portfolio_id = p.id AND s.currency IS NOT NULL
        UNION SELECT t.account_currency FROM ledger_transactions t
         WHERE t.portfolio_id = p.id AND t.account_currency IS NOT NULL
        UNION SELECT t.currency FROM ledger_transactions t WHERE t.portfolio_id = p.id
    ) x ON TRUE
),
first_needed AS (
    SELECT t.portfolio_id, MIN(t.trade_date) AS first_date FROM ledger_transactions t GROUP BY t.portfolio_id
)
SELECT n.base_currency, n.currency,
       (SELECT MIN(fn.first_date) FROM first_needed fn JOIN portfolios p ON p.id = fn.portfolio_id
         WHERE p.base_currency = n.base_currency) AS first_needed,
       f.first_date, f.last_date, COALESCE(f.days, 0) AS days, l.rate AS last_rate
FROM needed n
LEFT JOIN (
    SELECT base_currency, currency, MIN(rate_date) AS first_date, MAX(rate_date) AS last_date, COUNT(*) AS days
    FROM fx_rates GROUP BY base_currency, currency
) f ON f.base_currency = n.base_currency AND f.currency = n.currency
LEFT JOIN LATERAL (
    SELECT rate FROM fx_rates r WHERE r.base_currency = n.base_currency AND r.currency = n.currency
    ORDER BY r.rate_date DESC LIMIT 1
) l ON TRUE
ORDER BY n.base_currency, (n.currency = n.base_currency) DESC, n.currency
"""

SELECT_FX_SERIES = """
SELECT rate_date, rate, source FROM fx_rates
WHERE base_currency = %(base_currency)s AND currency = %(currency)s
  AND (%(date_gte)s::date IS NULL OR rate_date >= %(date_gte)s)
  AND (%(date_lte)s::date IS NULL OR rate_date <= %(date_lte)s)
ORDER BY rate_date
"""

# Forward-filled rate for one day: the latest fixing on or before it.
SELECT_FX_RATE_ON_OR_BEFORE = """
SELECT rate_date, rate FROM fx_rates
WHERE base_currency = %(base_currency)s AND currency = %(currency)s AND rate_date <= %(day)s
ORDER BY rate_date DESC LIMIT 1
"""
