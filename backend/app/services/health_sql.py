"""SQL for the daily health check."""

from __future__ import annotations

SELECT_READY = "SELECT 1 AS ready"

SELECT_LAST_ECB_RATE = """
SELECT MAX(rate_date) AS last_date FROM ecb_reference_rates
"""

SELECT_LAST_PORTFOLIO_DAYS = """
SELECT p.id, COALESCE(p.display_name, p.name) AS name, MAX(d.day) AS last_day
FROM portfolios p
LEFT JOIN portfolio_days d ON d.portfolio_id = p.id
GROUP BY p.id, p.display_name, p.name
ORDER BY p.id
"""
