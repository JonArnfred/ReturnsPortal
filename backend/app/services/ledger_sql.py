"""SQL for securities, portfolios, ledger transactions, and broker snapshots."""

from __future__ import annotations

UPSERT_PORTFOLIO = """
INSERT INTO portfolios (connection_id, name, base_currency)
VALUES (%(connection_id)s, %(name)s, %(base_currency)s)
ON CONFLICT (connection_id) DO UPDATE SET base_currency = EXCLUDED.base_currency
RETURNING id
"""

SELECT_SECURITY_IDS = """
SELECT id, uic, asset_type, currency FROM securities WHERE broker = %(broker)s
"""

SELECT_LEDGER_QUANTITIES = """
SELECT security_id, SUM(quantity) AS quantity
FROM ledger_transactions
WHERE connection_id = %(connection_id)s AND kind IN ('trade', 'corporate_action') AND trade_date <= %(as_of)s
GROUP BY security_id
"""

SELECT_LEDGER_CASH = """
SELECT account_key, account_currency AS currency, SUM(amount_account) AS balance
FROM ledger_transactions
WHERE connection_id = %(connection_id)s AND trade_date <= %(as_of)s AND amount_account IS NOT NULL
GROUP BY account_key, account_currency
"""

SELECT_LATEST_POSITION_SNAPSHOT = """
SELECT ps.security_id, ps.account_key, ps.quantity, s.symbol, ps.snapshot_date
FROM position_snapshots ps JOIN securities s ON s.id = ps.security_id
WHERE ps.connection_id = %(connection_id)s
  AND ps.snapshot_date = (SELECT MAX(snapshot_date) FROM position_snapshots WHERE connection_id = %(connection_id)s)
"""

SELECT_LATEST_CASH_SNAPSHOT = """
SELECT account_key, currency, cash_balance, snapshot_date
FROM cash_snapshots
WHERE connection_id = %(connection_id)s AND account_key <> ''
  AND snapshot_date = (SELECT MAX(snapshot_date) FROM cash_snapshots WHERE connection_id = %(connection_id)s)
"""

SELECT_LEDGER_SUMMARY = """
SELECT kind, COUNT(*) AS rows, MIN(trade_date) AS first_date, MAX(trade_date) AS last_date,
       ROUND(SUM(COALESCE(amount_base, 0)), 2) AS amount_base
FROM ledger_transactions WHERE connection_id = %(connection_id)s GROUP BY kind ORDER BY kind
"""

# Read models for the UI. Filters are appended by the service; ordering columns are whitelisted there.
SELECT_TRANSACTIONS_BASE = """
FROM ledger_transactions t
JOIN portfolios p ON p.id = t.portfolio_id
LEFT JOIN securities s ON s.id = t.security_id
LEFT JOIN broker_accounts a ON a.connection_id = t.connection_id AND a.account_key = t.account_key
"""

SELECT_TRANSACTIONS_COLUMNS = """
SELECT t.id, t.trade_date, t.value_date, t.kind, p.id AS portfolio_id,
       COALESCE(p.display_name, p.name) AS portfolio_name, a.account_id, a.currency AS account_label_currency,
       s.name AS security_name, s.ticker, s.mic, s.currency AS security_currency,
       t.quantity, t.price, t.currency, t.amount_local, t.account_currency, t.amount_account,
       t.base_currency, t.amount_base, t.fx_rate_base, t.description, t.related_ref,
       t.source_endpoint = 'cs/v1/audit/orderactivities' AS provisional
"""

SELECT_LATEST_POSITIONS = """
SELECT ps.id, ps.snapshot_date, ps.fetched_at, p.id AS portfolio_id, COALESCE(p.display_name, p.name) AS portfolio_name,
       a.account_id, a.currency AS account_label_currency,
       s.id AS security_id, s.name AS security_name, s.ticker, s.mic, s.asset_type,
       ps.quantity, ps.open_price, ps.current_price, ps.currency,
       ps.market_value_local, ps.market_value_base, ps.fx_rate_base, p.base_currency,
       COALESCE((ps.raw->'PositionView'->>'ProfitLossOnTrade')::numeric,
                NULLIF(ps.raw->>'fifoPnlUnrealized', '')::numeric) AS unrealized_local,
       COALESCE((ps.raw->'PositionView'->>'ProfitLossOnTradeInBaseCurrency')::numeric,
                NULLIF(ps.raw->>'fifoPnlUnrealized', '')::numeric * ps.fx_rate_base) AS unrealized_base,
       COALESCE(ps.raw->'PositionBase'->>'ExecutionTimeOpen', NULLIF(ps.raw->>'openDateTime', '')) AS opened_at
FROM position_snapshots ps
JOIN portfolios p ON p.id = ps.portfolio_id
JOIN securities s ON s.id = ps.security_id
LEFT JOIN broker_accounts a ON a.connection_id = ps.connection_id AND a.account_key = ps.account_key
WHERE ps.snapshot_date = (
    SELECT MAX(snapshot_date) FROM position_snapshots latest WHERE latest.connection_id = ps.connection_id
)
"""

SELECT_CASH_MOVEMENTS = """
SELECT t.id, t.trade_date, t.value_date, t.kind, COALESCE(p.display_name, p.name) AS portfolio_name,
       a.account_id, a.currency AS account_label_currency,
       t.currency, t.amount_local, t.account_currency, t.amount_account, t.base_currency, t.amount_base,
       t.related_ref, t.description
FROM ledger_transactions t
JOIN portfolios p ON p.id = t.portfolio_id
LEFT JOIN broker_accounts a ON a.connection_id = t.connection_id AND a.account_key = t.account_key
WHERE t.kind IN ('deposit', 'withdrawal', 'transfer')
  AND (p.reporting_start_date IS NULL OR t.trade_date >= p.reporting_start_date)
ORDER BY t.trade_date, t.related_ref, t.amount_local
"""

SELECT_LATEST_AUM = """
SELECT cs.portfolio_id, p.base_currency, cs.total_value, cs.cash_balance, cs.snapshot_date,
       -- Saxo: executed trades whose cash leg is not booked yet; counted in TotalValue but in neither
       -- cash nor positions. Other brokers have no such field.
       NULLIF(cs.raw->>'TransactionsNotBooked', '')::numeric AS unbooked
FROM cash_snapshots cs
JOIN portfolios p ON p.id = cs.portfolio_id
WHERE cs.account_key = '' AND cs.currency = p.base_currency
  AND cs.snapshot_date = (
    SELECT MAX(snapshot_date) FROM cash_snapshots latest WHERE latest.connection_id = cs.connection_id
  )
"""

SELECT_PORTFOLIOS = """
SELECT p.id, COALESCE(p.display_name, p.name) AS name, p.name AS broker_name, p.display_name,
       p.reporting_start_date, p.base_currency,
       p.connection_id, c.broker, c.environment, c.status AS connection_status, c.last_sync_finished_at
FROM portfolios p
LEFT JOIN broker_connections c ON c.id = p.connection_id
ORDER BY p.id
"""

SELECT_PORTFOLIO_ACCOUNTS = """
SELECT p.id AS portfolio_id, a.id, a.account_id, a.currency, a.active
FROM broker_accounts a
JOIN portfolios p ON p.connection_id = a.connection_id
ORDER BY p.id, a.currency, a.account_id
"""

SELECT_LATEST_CASH_BY_CURRENCY = """
SELECT cs.portfolio_id, cs.currency, SUM(cs.cash_balance) AS cash_balance
FROM cash_snapshots cs
WHERE cs.account_key <> ''
  AND cs.snapshot_date = (
    SELECT MAX(snapshot_date) FROM cash_snapshots latest WHERE latest.connection_id = cs.connection_id
  )
GROUP BY cs.portfolio_id, cs.currency
HAVING SUM(cs.cash_balance) <> 0
ORDER BY cs.portfolio_id, cs.currency
"""

SELECT_ORDERS = """
SELECT o.id, o.broker_order_id, o.portfolio_id, COALESCE(p.display_name, p.name) AS portfolio_name,
       a.account_id, a.currency AS account_currency,
       o.security_id, COALESCE(s.name, o.instrument_name) AS security_name, s.ticker, s.mic, s.asset_type,
       o.instrument_symbol, o.status, o.broker_status, o.is_open, o.buy_sell, o.order_type, o.duration,
       o.quantity, o.filled_quantity, o.price, o.average_fill_price, COALESCE(o.currency, s.currency) AS currency,
       o.placed_at, o.last_activity_at, o.expires_at, o.order_relation
FROM orders o
JOIN portfolios p ON p.id = o.portfolio_id
LEFT JOIN securities s ON s.id = o.security_id
LEFT JOIN broker_accounts a ON a.connection_id = o.connection_id AND a.account_key = o.account_key
WHERE p.reporting_start_date IS NULL OR o.is_open
   OR COALESCE(o.last_activity_at, o.placed_at)::date >= p.reporting_start_date
ORDER BY o.is_open DESC, o.placed_at DESC NULLS LAST, o.id DESC
"""

UPDATE_PORTFOLIO = """
UPDATE portfolios
SET display_name = CASE WHEN %(set_name)s THEN %(display_name)s ELSE display_name END,
    reporting_start_date = CASE WHEN %(set_start)s THEN %(reporting_start_date)s::date ELSE reporting_start_date END
WHERE id = %(portfolio_id)s
"""

# Provisional fills (from the order audit) whose order Saxo has since booked as a trade, within a day.
DELETE_SUPERSEDED_FILLS = """
DELETE FROM ledger_transactions f
WHERE f.connection_id = %(connection_id)s
  AND f.source_endpoint = 'cs/v1/audit/orderactivities'
  AND EXISTS (
      SELECT 1 FROM ledger_transactions t
      WHERE t.connection_id = f.connection_id
        AND t.source_endpoint = 'cs/v1/reports/trades'
        AND t.raw->>'OrderId' = f.raw->>'OrderId'
        AND ABS(t.trade_date - f.trade_date) <= 1
  )
"""


# Paged transactions: SELECT_TRANSACTIONS_COLUMNS + SELECT_TRANSACTIONS_BASE + WHERE (these filters,
# joined with AND) + TRANSACTIONS_PAGE. Sort keys map to expressions so ORDER BY never takes user text.
COUNT_TOTAL = "SELECT COUNT(*) AS total "
TRANSACTION_FILTERS = {
    "reporting_start": "(p.reporting_start_date IS NULL OR t.trade_date >= p.reporting_start_date)",
    "kinds": "t.kind = ANY(%(kinds)s)",
    "portfolio_id": "t.portfolio_id = %(portfolio_id)s",
    "account": "a.id = %(account)s",
    "date_gte": "t.trade_date >= %(date_gte)s",
    "date_lte": "t.trade_date <= %(date_lte)s",
    "search": (
        "(s.name ILIKE %(search)s OR s.ticker ILIKE %(search)s OR t.description ILIKE %(search)s"
        " OR (s.ticker || ':' || COALESCE(s.mic, '')) ILIKE %(search)s)"
    ),
}
TRANSACTION_TRADE_TYPES = {
    "buy": "(t.kind = 'trade' AND t.quantity > 0)",
    "sell": "(t.kind = 'trade' AND t.quantity < 0)",
    "corporate_action": "t.kind = 'corporate_action'",
}
TRANSACTION_ORDER_COLUMNS = {
    "trade_date": "t.trade_date",
    "kind": "t.kind",
    "security_name": "s.name",
    "quantity": "t.quantity",
    "amount_local": "t.amount_local",
    "amount_base": "t.amount_base",
    "portfolio_name": "COALESCE(p.display_name, p.name)",
}
TRANSACTIONS_PAGE = " ORDER BY {} {} NULLS LAST, t.id DESC OFFSET %(offset)s LIMIT %(limit)s"
