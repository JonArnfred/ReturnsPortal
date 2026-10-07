"""SQL for application settings and the reporting-currency checks."""

from __future__ import annotations

SELECT_SETTING = """
SELECT value FROM app_settings WHERE key = %(key)s
"""

UPSERT_SETTING = """
INSERT INTO app_settings (key, value, updated_at)
VALUES (%(key)s, %(value)s, CURRENT_TIMESTAMP)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
"""

# Currencies on the latest ECB fixing: the ones a reporting currency can be crossed into.
SELECT_ECB_CURRENCIES = """
SELECT DISTINCT currency FROM ecb_reference_rates
WHERE rate_date = (SELECT MAX(rate_date) FROM ecb_reference_rates)
"""

# Saxo books in the client currency, so a Saxo connection pins the reporting currency to it.
SELECT_SAXO_CLIENT_CURRENCIES = """
SELECT DISTINCT base_currency FROM broker_connections
WHERE broker = 'saxo' AND base_currency IS NOT NULL
"""

# Per portfolio: the currency it is booked in and the one its derived tables were last built in.
SELECT_PORTFOLIO_CURRENCIES = """
SELECT p.id AS portfolio_id, COALESCE(p.display_name, p.name) AS portfolio_name,
       p.base_currency AS booked_currency,
       (SELECT d.base_currency FROM portfolio_days d WHERE d.portfolio_id = p.id ORDER BY d.day DESC LIMIT 1)
           AS built_currency
FROM portfolios p
ORDER BY p.id
"""
