-- Rebuilds the positions and position_transactions of one portfolio (optionally one security)
-- from the ledger. See documentation/VISION.md 3.1.
--
-- Rules
--   * Quantity events are trades, one by one, and corporate actions merged per day (Saxo books a
--     split as sell-all plus buy, and a ticker change as sell-all plus buy-all).
--   * A position opens with the first event that moves the quantity away from zero and closes
--     with the event that brings it back to zero; the next event opens a new position.
--   * Events within a day are ordered by the broker's execution time (raw TradeExecutionTime),
--     then by ledger id.
--   * A corporate action that changes the quantity without opening or closing is a split: the
--     shares traded before it are scaled onto the later basis, so share counts and average prices
--     are on today's split-adjusted basis, like the price history. Splits the ledger never booked
--     (the position was closed before the split) are inferred from the trade price against the
--     last close, snapped to a whole ratio and carried forward, exactly as the PnL engine does
--     (100_rebuild_pnl.sql); the resulting basis factor is stored per event and per position.
--   * A day whose corporate-action legs net to zero while nothing is held opens no position.
--   * Base amounts follow the engine's rule: the account amount when the account is in the base
--     currency, else the broker's reported base amount.
--   * Income (dividend, withholding tax, lending income) and costs (commission, fee, tax) belong to
--     the position of the trade they were booked against; unlinked rows go to the position open on
--     their date, else the last one opened before. A cost booked on a purchase is funding cash.
--   * Local amounts are in the instrument currency; a row booked in another currency is converted
--     with the FX of its trade, else of the position's latest trade on or before its date.
--   * Positions are upserted on (portfolio, security, opened), so ids survive rebuilds; positions
--     the ledger no longer supports are deleted.
CREATE OR REPLACE FUNCTION rebuild_positions(p_portfolio_id bigint, p_security_id bigint DEFAULT NULL)
RETURNS TABLE (position_rows bigint, link_rows bigint)
LANGUAGE plpgsql AS $$
DECLARE
    v_base char(3);
    v_position_rows bigint := 0;
    v_link_rows bigint := 0;
    v_money_rows bigint := 0;
BEGIN
    SELECT p.base_currency INTO v_base FROM portfolios p WHERE p.id = p_portfolio_id;
    IF v_base IS NULL THEN
        RAISE EXCEPTION 'portfolio % does not exist', p_portfolio_id;
    END IF;

    DROP TABLE IF EXISTS pg_temp.rp_events;
    DROP TABLE IF EXISTS pg_temp.rp_episodes;
    DROP TABLE IF EXISTS pg_temp.rp_money;

    ------------------------------------------------------------------------------------------
    -- Quantity events with running quantity, episode number and split factor
    ------------------------------------------------------------------------------------------
    CREATE TEMP TABLE rp_events ON COMMIT DROP AS
    WITH raw AS (
        SELECT t.id, t.security_id, t.kind, t.trade_date, COALESCE(t.quantity, 0) AS quantity, t.price,
               COALESCE(t.amount_local, 0) AS amount_local,
               COALESCE(CASE WHEN t.account_currency = v_base THEN t.amount_account END, t.amount_base, 0) AS amount_base,
               t.fx_rate_base, t.currency, t.broker_ref,
               -- Saxo stores TradeExecutionTime, the IBKR mapping writes executed_at.
               COALESCE(NULLIF(t.raw->>'TradeExecutionTime', ''), NULLIF(t.raw->>'executed_at', ''))::timestamptz AS executed_at
        FROM ledger_transactions t
        WHERE t.portfolio_id = p_portfolio_id AND t.security_id IS NOT NULL
          AND (p_security_id IS NULL OR t.security_id = p_security_id)
          AND t.kind IN ('trade', 'corporate_action')
    ),
    events AS (
        SELECT r.security_id, r.trade_date, r.executed_at, r.id AS ord, 'trade'::text AS kind, r.quantity, r.price,
               r.amount_local, r.amount_base, r.fx_rate_base, r.currency, r.broker_ref, ARRAY[r.id] AS ids
        FROM raw r WHERE r.kind = 'trade'
        UNION ALL
        SELECT r.security_id, r.trade_date, MIN(r.executed_at), MIN(r.id), 'corporate_action', SUM(r.quantity), NULL,
               0, 0, NULL, MIN(r.currency), NULL, ARRAY_AGG(r.id ORDER BY r.id)
        FROM raw r WHERE r.kind = 'corporate_action'
        GROUP BY r.security_id, r.trade_date
    ),
    running AS (
        SELECT e.*,
               SUM(e.quantity) OVER w AS qty_after,
               SUM(e.quantity) OVER w - e.quantity AS qty_before
        FROM events e
        WINDOW w AS (PARTITION BY e.security_id ORDER BY e.trade_date, e.executed_at NULLS LAST, e.ord)
    ),
    numbered AS (
        SELECT r.*,
               COALESCE(SUM(CASE WHEN r.qty_after = 0 THEN 1 ELSE 0 END) OVER (
                   PARTITION BY r.security_id ORDER BY r.trade_date, r.executed_at NULLS LAST, r.ord
                   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS episode_no,
               CASE WHEN r.kind = 'corporate_action' AND r.qty_before <> 0 AND r.qty_after <> 0
                    THEN r.qty_after / r.qty_before ELSE 1 END AS ratio
        FROM running r
    ),
    factored AS (
        SELECT n.*,
               MIN(n.trade_date) OVER ep AS opened,
               MAX(n.trade_date) OVER ep AS last_date,
               FIRST_VALUE(n.quantity) OVER (ep ORDER BY n.trade_date, n.executed_at NULLS LAST, n.ord) AS first_quantity,
               LAST_VALUE(n.qty_after) OVER (ep ORDER BY n.trade_date, n.executed_at NULLS LAST, n.ord
                   ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS final_quantity,
               BOOL_OR(n.quantity <> 0) OVER ep AS real_episode,
               -- product of the booked split ratios after the event: brings its shares onto the later basis
               numeric_product(n.ratio) OVER ep
                   / numeric_product(n.ratio) OVER (ep ORDER BY n.trade_date, n.executed_at NULLS LAST, n.ord)
                   AS factor
        FROM numbered n
        WINDOW ep AS (PARTITION BY n.security_id, n.episode_no)
    ),
    -- Splits the ledger never booked: the trade price (on the booked basis) against the last close.
    implied AS (
        SELECT f.*,
               CASE WHEN f.kind = 'trade' AND f.price > 0 AND c.close > 0
                    THEN snap_split_ratio(f.price / f.factor / c.close) END AS implied_obs
        FROM factored f
        LEFT JOIN LATERAL (
            SELECT d.close FROM daily_prices d
            WHERE f.kind = 'trade' AND d.security_id = f.security_id AND d.price_date <= f.trade_date
            ORDER BY d.price_date DESC LIMIT 1
        ) c ON TRUE
    ),
    carried AS (
        SELECT i.*, COUNT(i.implied_obs) OVER (PARTITION BY i.security_id ORDER BY i.trade_date, i.executed_at NULLS LAST, i.ord) AS grp
        FROM implied i
    )
    SELECT c.*,
           COALESCE(FIRST_VALUE(c.implied_obs) OVER (PARTITION BY c.security_id, c.grp
               ORDER BY c.trade_date, c.executed_at NULLS LAST, c.ord), 1) AS inferred
    FROM carried c;

    ------------------------------------------------------------------------------------------
    -- One row per episode
    ------------------------------------------------------------------------------------------
    CREATE TEMP TABLE rp_episodes ON COMMIT DROP AS
    SELECT e.security_id, e.episode_no, e.opened,
           CASE WHEN e.final_quantity = 0 THEN e.last_date END AS closed,
           e.final_quantity AS quantity,
           (ARRAY_AGG(e.factor * e.inferred ORDER BY e.trade_date DESC, e.executed_at DESC NULLS LAST, e.ord DESC))[1]
               AS basis_factor,
           CASE WHEN e.first_quantity < 0 THEN 'short' ELSE 'long' END AS position_type,
           COALESCE(s.currency, MIN(e.currency)) AS currency,
           COUNT(*) FILTER (WHERE e.kind = 'trade' AND e.quantity > 0)::integer AS buys,
           COUNT(*) FILTER (WHERE e.kind = 'trade' AND e.quantity < 0)::integer AS sells,
           SUM(CASE WHEN e.kind = 'trade' AND e.quantity > 0 THEN e.quantity * e.factor * e.inferred ELSE 0 END)
               AS shares_bought,
           SUM(CASE WHEN e.kind = 'trade' AND e.quantity < 0 THEN -e.quantity * e.factor * e.inferred ELSE 0 END)
               AS shares_sold,
           SUM(CASE WHEN e.kind = 'trade' AND e.quantity > 0 THEN e.quantity * COALESCE(e.price, 0) ELSE 0 END) AS buy_value_local,
           SUM(CASE WHEN e.kind = 'trade' AND e.quantity < 0 THEN -e.quantity * COALESCE(e.price, 0) ELSE 0 END) AS sell_value_local,
           SUM(CASE WHEN e.kind = 'trade' AND e.quantity > 0 THEN ABS(e.amount_local) ELSE 0 END) AS buy_cash_local,
           SUM(CASE WHEN e.kind = 'trade' AND e.quantity < 0 THEN e.amount_local ELSE 0 END) AS sell_cash_local,
           SUM(CASE WHEN e.kind = 'trade' AND e.quantity > 0 THEN ABS(e.amount_base) ELSE 0 END) AS buy_cash_base,
           SUM(CASE WHEN e.kind = 'trade' AND e.quantity < 0 THEN e.amount_base ELSE 0 END) AS sell_cash_base
    FROM rp_events e
    JOIN securities s ON s.id = e.security_id
    WHERE e.real_episode
    GROUP BY e.security_id, e.episode_no, e.opened, e.last_date, e.final_quantity, e.first_quantity, s.currency;

    ------------------------------------------------------------------------------------------
    -- Income and cost rows, attached to an episode and converted to the instrument currency
    ------------------------------------------------------------------------------------------
    CREATE TEMP TABLE rp_money ON COMMIT DROP AS
    WITH money AS (
        SELECT t.id, t.security_id, t.kind, t.trade_date, t.currency,
               COALESCE(t.amount_local, 0) AS amount_local,
               COALESCE(CASE WHEN t.account_currency = v_base THEN t.amount_account END, t.amount_base, 0) AS amount_base,
               t.related_ref
        FROM ledger_transactions t
        WHERE t.portfolio_id = p_portfolio_id AND t.security_id IS NOT NULL
          AND (p_security_id IS NULL OR t.security_id = p_security_id)
          AND t.kind IN ('dividend', 'withholding_tax', 'lending_income', 'commission', 'fee', 'tax')
    ),
    linked AS (
        SELECT m.*, e.episode_no AS linked_episode, e.quantity AS linked_quantity, e.fx_rate_base AS linked_fx
        FROM money m
        LEFT JOIN rp_events e
               ON e.kind = 'trade' AND e.security_id = m.security_id AND e.broker_ref = m.related_ref
    ),
    resolved AS (
        SELECT l.*,
               COALESCE(l.linked_episode, fallback.episode_no) AS episode_no,
               COALESCE(l.linked_fx, latest.fx_rate_base) AS fx
        FROM linked l
        LEFT JOIN LATERAL (
            SELECT ep.episode_no FROM rp_episodes ep
            WHERE l.linked_episode IS NULL AND ep.security_id = l.security_id AND ep.opened <= l.trade_date
            ORDER BY ep.opened DESC LIMIT 1
        ) fallback ON TRUE
        LEFT JOIN LATERAL (
            SELECT e.fx_rate_base FROM rp_events e
            WHERE l.linked_episode IS NULL AND e.kind = 'trade' AND e.security_id = l.security_id
              AND e.episode_no = fallback.episode_no AND e.trade_date <= l.trade_date
            ORDER BY e.trade_date DESC, e.executed_at DESC NULLS LAST, e.ord DESC LIMIT 1
        ) latest ON TRUE
    )
    SELECT r.id, r.security_id, r.episode_no, r.trade_date,
           CASE WHEN r.kind IN ('dividend', 'withholding_tax', 'lending_income') THEN 'income' ELSE 'cost' END AS role,
           (r.linked_episode IS NOT NULL AND r.linked_quantity > 0
                AND r.kind IN ('commission', 'fee', 'tax')) AS funding,
           r.amount_base,
           CASE WHEN r.currency = ep.currency OR r.fx IS NULL OR r.fx = 0 THEN r.amount_local
                ELSE r.amount_base / r.fx END AS amount_local
    FROM resolved r
    JOIN rp_episodes ep ON ep.security_id = r.security_id AND ep.episode_no = r.episode_no;

    ------------------------------------------------------------------------------------------
    -- Upsert positions (ids survive), drop the ones the ledger no longer supports
    ------------------------------------------------------------------------------------------
    INSERT INTO positions (
        portfolio_id, security_id, opened, closed, position_type, currency, base_currency, quantity, basis_factor,
        buys, sells, shares_bought, shares_sold, avg_buy_price, avg_sell_price,
        buy_cash_local, sell_cash_local, buy_cash_base, sell_cash_base,
        invested_local, invested_base, dividends_local, dividends_base, costs_local, costs_base, rebuilt_at
    )
    SELECT p_portfolio_id, ep.security_id, ep.opened, ep.closed, ep.position_type, ep.currency, v_base, ep.quantity,
           ep.basis_factor, ep.buys, ep.sells, ep.shares_bought, ep.shares_sold,
           CASE WHEN ep.shares_bought <> 0 THEN ep.buy_value_local / ep.shares_bought END,
           CASE WHEN ep.shares_sold <> 0 THEN ep.sell_value_local / ep.shares_sold END,
           ep.buy_cash_local, ep.sell_cash_local, ep.buy_cash_base, ep.sell_cash_base,
           ep.buy_cash_local + COALESCE(m.funding_local, 0),
           ep.buy_cash_base + COALESCE(m.funding_base, 0),
           COALESCE(m.dividends_local, 0), COALESCE(m.dividends_base, 0),
           COALESCE(m.costs_local, 0), COALESCE(m.costs_base, 0),
           CURRENT_TIMESTAMP
    FROM rp_episodes ep
    LEFT JOIN (
        SELECT x.security_id, x.episode_no,
               SUM(CASE WHEN x.role = 'income' THEN x.amount_local ELSE 0 END) AS dividends_local,
               SUM(CASE WHEN x.role = 'income' THEN x.amount_base ELSE 0 END) AS dividends_base,
               SUM(CASE WHEN x.role = 'cost' THEN x.amount_local ELSE 0 END) AS costs_local,
               SUM(CASE WHEN x.role = 'cost' THEN x.amount_base ELSE 0 END) AS costs_base,
               SUM(CASE WHEN x.funding THEN ABS(x.amount_local) ELSE 0 END) AS funding_local,
               SUM(CASE WHEN x.funding THEN ABS(x.amount_base) ELSE 0 END) AS funding_base
        FROM rp_money x GROUP BY x.security_id, x.episode_no
    ) m ON m.security_id = ep.security_id AND m.episode_no = ep.episode_no
    ON CONFLICT (portfolio_id, security_id, opened) DO UPDATE SET
        closed = EXCLUDED.closed, position_type = EXCLUDED.position_type, currency = EXCLUDED.currency,
        base_currency = EXCLUDED.base_currency, quantity = EXCLUDED.quantity, basis_factor = EXCLUDED.basis_factor,
        buys = EXCLUDED.buys, sells = EXCLUDED.sells,
        shares_bought = EXCLUDED.shares_bought, shares_sold = EXCLUDED.shares_sold,
        avg_buy_price = EXCLUDED.avg_buy_price, avg_sell_price = EXCLUDED.avg_sell_price,
        buy_cash_local = EXCLUDED.buy_cash_local, sell_cash_local = EXCLUDED.sell_cash_local,
        buy_cash_base = EXCLUDED.buy_cash_base, sell_cash_base = EXCLUDED.sell_cash_base,
        invested_local = EXCLUDED.invested_local, invested_base = EXCLUDED.invested_base,
        dividends_local = EXCLUDED.dividends_local, dividends_base = EXCLUDED.dividends_base,
        costs_local = EXCLUDED.costs_local, costs_base = EXCLUDED.costs_base,
        rebuilt_at = EXCLUDED.rebuilt_at;
    GET DIAGNOSTICS v_position_rows = ROW_COUNT;

    DELETE FROM positions p
    WHERE p.portfolio_id = p_portfolio_id
      AND (p_security_id IS NULL OR p.security_id = p_security_id)
      AND NOT EXISTS (
          SELECT 1 FROM rp_episodes ep WHERE ep.security_id = p.security_id AND ep.opened = p.opened
      );

    ------------------------------------------------------------------------------------------
    -- Links
    ------------------------------------------------------------------------------------------
    DELETE FROM position_transactions pt
    USING positions p
    WHERE pt.position_id = p.id AND p.portfolio_id = p_portfolio_id
      AND (p_security_id IS NULL OR p.security_id = p_security_id);

    INSERT INTO position_transactions (transaction_id, position_id, role, funding, basis_factor)
    SELECT UNNEST(e.ids), p.id, e.kind, FALSE, e.factor * e.inferred
    FROM rp_events e
    JOIN rp_episodes ep ON ep.security_id = e.security_id AND ep.episode_no = e.episode_no
    JOIN positions p ON p.portfolio_id = p_portfolio_id AND p.security_id = ep.security_id AND p.opened = ep.opened;
    GET DIAGNOSTICS v_link_rows = ROW_COUNT;

    INSERT INTO position_transactions (transaction_id, position_id, role, funding, basis_factor)
    SELECT m.id, p.id, m.role, m.funding, NULL
    FROM rp_money m
    JOIN rp_episodes ep ON ep.security_id = m.security_id AND ep.episode_no = m.episode_no
    JOIN positions p ON p.portfolio_id = p_portfolio_id AND p.security_id = ep.security_id AND p.opened = ep.opened;
    GET DIAGNOSTICS v_money_rows = ROW_COUNT;

    DROP TABLE IF EXISTS pg_temp.rp_money;
    DROP TABLE IF EXISTS pg_temp.rp_episodes;
    DROP TABLE IF EXISTS pg_temp.rp_events;

    RETURN QUERY SELECT v_position_rows, v_link_rows + v_money_rows;
END;
$$;
