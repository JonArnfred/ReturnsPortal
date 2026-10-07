"""SQL for daily prices and per-security price sources."""

from __future__ import annotations

SELECT_SECURITIES_FOR_PRICES = """
SELECT s.id, s.uic, s.asset_type, s.ticker, s.mic, s.currency, s.name,
       l.first_needed, l.last_needed,
       p.source, p.yahoo_symbol, p.last_price_date, p.last_error
FROM securities s
LEFT JOIN (
    SELECT security_id, MIN(trade_date) AS first_needed, MAX(trade_date) AS last_needed
    FROM ledger_transactions WHERE security_id IS NOT NULL GROUP BY security_id
) l ON l.security_id = s.id
LEFT JOIN security_price_sources p ON p.security_id = s.id
WHERE s.broker = %(broker)s
ORDER BY s.id
"""

UPSERT_PRICE_SOURCE = """
INSERT INTO security_price_sources (
    security_id, source, yahoo_symbol, first_needed, first_price_date, last_price_date, bars,
    last_fetched_at, last_error, updated_at
)
SELECT %(security_id)s, %(source)s, %(yahoo_symbol)s, %(first_needed)s,
       MIN(price_date), MAX(price_date), COUNT(*), CURRENT_TIMESTAMP, %(last_error)s, CURRENT_TIMESTAMP
FROM daily_prices WHERE security_id = %(security_id)s
ON CONFLICT (security_id) DO UPDATE SET
    source = EXCLUDED.source,
    yahoo_symbol = COALESCE(EXCLUDED.yahoo_symbol, security_price_sources.yahoo_symbol),
    first_needed = EXCLUDED.first_needed,
    first_price_date = EXCLUDED.first_price_date,
    last_price_date = EXCLUDED.last_price_date,
    bars = EXCLUDED.bars,
    last_fetched_at = EXCLUDED.last_fetched_at,
    last_error = EXCLUDED.last_error,
    updated_at = CURRENT_TIMESTAMP
"""

SELECT_PRICE_STATUS = """
SELECT s.id AS security_id, s.name AS security_name, s.ticker, s.mic, s.asset_type,
       COALESCE(p.source, 'none') AS source, p.yahoo_symbol,
       COALESCE(p.first_needed, l.first_needed) AS first_needed, l.last_needed,
       p.first_price_date, p.last_price_date, COALESCE(p.bars, 0) AS bars,
       p.last_fetched_at, p.last_error,
       (SELECT d.currency FROM daily_prices d WHERE d.security_id = s.id ORDER BY d.price_date DESC LIMIT 1)
           AS currency,
       (SELECT d.close FROM daily_prices d WHERE d.security_id = s.id ORDER BY d.price_date DESC LIMIT 1) AS last_close,
       EXISTS (
           SELECT 1 FROM position_snapshots ps
           WHERE ps.security_id = s.id AND ps.snapshot_date = (
               SELECT MAX(snapshot_date) FROM position_snapshots latest WHERE latest.connection_id = ps.connection_id
           )
       ) AS held
FROM securities s
LEFT JOIN security_price_sources p ON p.security_id = s.id
LEFT JOIN (
    SELECT security_id, MIN(trade_date) AS first_needed, MAX(trade_date) AS last_needed
    FROM ledger_transactions WHERE security_id IS NOT NULL GROUP BY security_id
) l ON l.security_id = s.id
ORDER BY s.name NULLS LAST, s.ticker
"""

SELECT_DAILY_PRICES = """
SELECT price_date, open, high, low, close, volume, currency, source
FROM daily_prices
WHERE security_id = %(security_id)s
  AND (%(date_gte)s::date IS NULL OR price_date >= %(date_gte)s)
  AND (%(date_lte)s::date IS NULL OR price_date <= %(date_lte)s)
ORDER BY price_date
"""

# A broker's own mark replaces the stored close of that day. Days up to and including a booked
# quantity-changing corporate action keep the source's close: marks are as of their day (a split
# booked after the close is not in that day's mark), while the price history must be on the
# split-adjusted basis the engine scales ledger quantities to.
UPSERT_BROKER_MARK = """
INSERT INTO daily_prices (security_id, price_date, open, high, low, close, volume, currency, source, fetched_at)
SELECT %(security_id)s, %(price_date)s, NULL, NULL, NULL, %(close)s, NULL, %(currency)s, %(source)s, CURRENT_TIMESTAMP
WHERE NOT EXISTS (
    SELECT 1 FROM ledger_transactions t
    WHERE t.security_id = %(security_id)s AND t.kind = 'corporate_action'
      AND COALESCE(t.quantity, 0) <> 0 AND t.trade_date >= %(price_date)s
)
ON CONFLICT (security_id, price_date) DO UPDATE SET
    open = NULL, high = NULL, low = NULL, volume = NULL,
    close = EXCLUDED.close, currency = EXCLUDED.currency, source = EXCLUDED.source, fetched_at = EXCLUDED.fetched_at
"""

SELECT_BROKER_MARK_DATES = """
SELECT price_date FROM daily_prices
WHERE security_id = %(security_id)s AND source = 'ibkr' AND price_date >= %(since)s
"""
