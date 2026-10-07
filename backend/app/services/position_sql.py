"""SQL for the positions table: rebuild trigger and read models."""

from __future__ import annotations

REBUILD = "SELECT * FROM rebuild_positions(%(portfolio_id)s, %(security_id)s)"

SELECT_PORTFOLIO_IDS = "SELECT id FROM portfolios ORDER BY id"

# Positions with their names and, for open ones, the latest broker mark of the security and the
# engine's latest valuation (pnl_days), which is newer than the mark when the broker snapshot lags.
SELECT_POSITIONS = """
WITH marks AS (
    SELECT ps.portfolio_id, ps.security_id, ps.snapshot_date,
           MAX(ps.current_price) AS current_price,
           MAX(ps.fx_rate_base) AS fx_rate_base,
           SUM(ps.market_value_base) AS market_value_base
    FROM position_snapshots ps
    WHERE ps.snapshot_date = (
        SELECT MAX(snapshot_date) FROM position_snapshots latest WHERE latest.connection_id = ps.connection_id
    )
    GROUP BY ps.portfolio_id, ps.security_id, ps.snapshot_date
)
SELECT pos.*, p.reporting_start_date, COALESCE(p.display_name, p.name) AS portfolio_name,
       opening.quantity_prev * opening.price_prev AS opening_value_local,
       CASE WHEN opening.price_prev IS NOT NULL AND opening.fx_prev IS NOT NULL
            THEN opening.prev_market_value_base END AS opening_value_base,
       activity.*,
       s.name AS security_name, s.ticker, s.mic, s.asset_type,
       m.current_price, m.fx_rate_base, m.market_value_base AS mark_value_base, m.snapshot_date AS mark_date,
       engine.*
FROM positions pos
JOIN portfolios p ON p.id = pos.portfolio_id
JOIN securities s ON s.id = pos.security_id
LEFT JOIN marks m ON m.portfolio_id = pos.portfolio_id AND m.security_id = pos.security_id AND pos.closed IS NULL
LEFT JOIN LATERAL (
    SELECT d.quantity AS engine_quantity, d.price AS engine_price, d.price_date AS engine_price_date,
           d.market_value_local AS engine_value_local, d.market_value_base AS engine_value_base
    FROM pnl_days d
    WHERE pos.closed IS NULL AND d.portfolio_id = pos.portfolio_id AND d.security_id = pos.security_id
      AND d.position_kind = 'security' AND d.price IS NOT NULL AND d.fx IS NOT NULL
    ORDER BY d.day DESC
    LIMIT 1
) engine ON TRUE
LEFT JOIN pnl_days opening ON opening.portfolio_id = pos.portfolio_id
    AND opening.security_id = pos.security_id AND opening.position_kind = 'security'
    AND opening.day = p.reporting_start_date AND pos.opened < p.reporting_start_date
LEFT JOIN LATERAL (
    WITH money AS (
        SELECT t.*, pt.role, pt.funding, pt.basis_factor AS trade_basis,
               COALESCE(CASE WHEN t.account_currency = pos.base_currency THEN t.amount_account END,
                        t.amount_base, 0) AS base_amount,
               COALESCE(linked.fx_rate_base, latest.fx_rate_base) AS money_fx
        FROM position_transactions pt JOIN ledger_transactions t ON t.id = pt.transaction_id
        LEFT JOIN LATERAL (
            SELECT tr.fx_rate_base FROM position_transactions link
            JOIN ledger_transactions tr ON tr.id = link.transaction_id
            WHERE link.position_id = pos.id AND tr.kind = 'trade' AND tr.broker_ref = t.related_ref
            ORDER BY tr.id DESC LIMIT 1
        ) linked ON TRUE
        LEFT JOIN LATERAL (
            SELECT tr.fx_rate_base FROM position_transactions link
            JOIN ledger_transactions tr ON tr.id = link.transaction_id
            WHERE link.position_id = pos.id AND tr.kind = 'trade' AND tr.trade_date <= t.trade_date
            ORDER BY tr.trade_date DESC, tr.id DESC LIMIT 1
        ) latest ON TRUE
        WHERE pt.position_id = pos.id AND p.reporting_start_date IS NOT NULL
          AND t.trade_date >= p.reporting_start_date
    ), normalized AS (
        SELECT m.*, CASE WHEN role IN ('trade', 'corporate_action') OR currency = pos.currency
                                  OR money_fx IS NULL OR money_fx = 0 THEN amount_local
                        ELSE base_amount / money_fx END AS local_amount
        FROM money m
    )
    SELECT COUNT(*) FILTER (WHERE role = 'trade' AND quantity > 0)::integer AS period_buys,
           COUNT(*) FILTER (WHERE role = 'trade' AND quantity < 0)::integer AS period_sells,
           COALESCE(SUM(quantity * trade_basis) FILTER (WHERE role = 'trade' AND quantity > 0), 0)
               AS period_shares_bought,
           COALESCE(SUM(-quantity * trade_basis) FILTER (WHERE role = 'trade' AND quantity < 0), 0)
               AS period_shares_sold,
           COALESCE(SUM(ABS(local_amount)) FILTER (WHERE role = 'trade' AND quantity > 0), 0) AS period_buy_cash_local,
           COALESCE(SUM(local_amount) FILTER (WHERE role = 'trade' AND quantity < 0), 0) AS period_sell_cash_local,
           COALESCE(SUM(local_amount) FILTER (WHERE role = 'income'), 0) AS period_dividends_local,
           COALESCE(SUM(local_amount) FILTER (WHERE role = 'cost'), 0) AS period_costs_local,
           COALESCE(SUM(ABS(local_amount)) FILTER (WHERE funding), 0) AS period_funding_local,
           COALESCE(SUM(ABS(base_amount)) FILTER (WHERE role = 'trade' AND quantity > 0), 0) AS period_buy_cash_base,
           COALESCE(SUM(base_amount) FILTER (WHERE role = 'trade' AND quantity < 0), 0) AS period_sell_cash_base,
           COALESCE(SUM(base_amount) FILTER (WHERE role = 'income'), 0) AS period_dividends_base,
           COALESCE(SUM(base_amount) FILTER (WHERE role = 'cost'), 0) AS period_costs_base,
           COALESCE(SUM(ABS(base_amount)) FILTER (WHERE funding), 0) AS period_funding_base
    FROM normalized
) activity ON TRUE
WHERE (%(position_id)s::bigint IS NULL OR pos.id = %(position_id)s)
  AND (p.reporting_start_date IS NULL OR pos.closed IS NULL OR pos.closed >= p.reporting_start_date)
ORDER BY pos.portfolio_id, pos.security_id, pos.opened
"""

SELECT_POSITION_TRANSACTIONS = """
SELECT t.id, t.kind, t.trade_date, t.quantity, t.price, t.currency, t.amount_local, t.amount_base,
       pt.role, pt.funding, pt.basis_factor
FROM position_transactions pt
JOIN ledger_transactions t ON t.id = pt.transaction_id
WHERE pt.position_id = %(position_id)s
ORDER BY t.trade_date, t.id
"""
