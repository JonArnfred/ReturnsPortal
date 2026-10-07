-- The PnL engine: rebuilds pnl_days, portfolio_days and reconciliation_issues for one portfolio
-- from the ledger, daily_prices and fx_rates. See documentation/VISION.md section 4.
--
-- Conventions
--   * Every calendar day from the first ledger row to p_through (default: today) is a row; prices
--     and FX are carried forward (never interpolated), and gaps become reconciliation_issues.
--   * Each ledger row has one base value used for both of its legs: the account amount when the
--     account is in the base currency (exact), otherwise the broker's reported base amount. The two
--     legs of a transfer between own accounts share the base-currency leg's amount, so a currency
--     conversion nets to zero and its spread shows up as FX effect on the currency bought.
--   * Securities are held on the split-adjusted basis of the price history: raw ledger quantities
--     are scaled by the product of the split ratios booked after the day (corporate actions that
--     change quantity without cash and without opening or closing the position).
--   * A corporate action that closes one security and opens another the same day moves the closing
--     position's carried value into the new one, so neither side books a fake gain or loss.
--   * Cash per currency is a position with price 1 (VISION 4.4); deposits and withdrawals are the
--     only external flows. Dividends, interest and costs are effects of the position they belong
--     to (the security when linked, else the cash currency they were booked in).
--   * Effects are stored rounded to 8 decimals with the interaction effect defined as the residual,
--     so daily_pnl == market_value − prev_market_value − flow holds exactly in the stored numbers,
--     and the sum over positions equals ΔNAV − external flow to the last øre.
CREATE OR REPLACE FUNCTION rebuild_pnl(p_portfolio_id bigint, p_through date DEFAULT NULL)
RETURNS TABLE (position_rows bigint, portfolio_rows bigint, issue_rows bigint)
LANGUAGE plpgsql AS $$
DECLARE
    v_base char(3);
    v_first date;
    v_last date;
    v_position_rows bigint := 0;
    v_portfolio_rows bigint := 0;
    v_issue_rows bigint := 0;
BEGIN
    SELECT p.base_currency INTO v_base FROM portfolios p WHERE p.id = p_portfolio_id;
    IF v_base IS NULL THEN
        RAISE EXCEPTION 'portfolio % does not exist', p_portfolio_id;
    END IF;
    v_last := COALESCE(p_through, CURRENT_DATE);
    SELECT MIN(t.trade_date) INTO v_first FROM ledger_transactions t
    WHERE t.portfolio_id = p_portfolio_id AND t.trade_date <= v_last;

    DELETE FROM reconciliation_issues r WHERE r.portfolio_id = p_portfolio_id;
    DELETE FROM portfolio_days r WHERE r.portfolio_id = p_portfolio_id;
    DELETE FROM pnl_days r WHERE r.portfolio_id = p_portfolio_id;
    IF v_first IS NULL THEN
        RETURN QUERY SELECT 0::bigint, 0::bigint, 0::bigint;
        RETURN;
    END IF;

    ------------------------------------------------------------------------------------------
    -- Position days
    ------------------------------------------------------------------------------------------
    INSERT INTO pnl_days (
        portfolio_id, position_key, day, position_kind, security_id, currency, base_currency,
        quantity_prev, quantity, trade_quantity, basis_factor, inferred_split,
        price_prev, price, price_date, price_source, fx_prev, fx, fx_date, execution_price, execution_fx,
        market_value_local, market_value_base, prev_market_value_base,
        trade_flow_local, trade_flow_base, flow_base,
        price_effect_base, price_effect_local, fx_effect_base, interaction_effect_base,
        dividend_effect_base, dividend_effect_local, interest_effect_base, cost_effect_base, cost_effect_local,
        daily_pnl_base, daily_pnl_local, daily_return_pct, constant_currency_return_pct,
        total_pnl_base, total_pnl_local
    )
    WITH days AS (
        SELECT d::date AS day FROM generate_series(v_first, v_last, interval '1 day') AS d
    ),
    ledger AS (
        SELECT t.id, t.kind, t.trade_date AS day, t.security_id, t.quantity, t.price, t.currency,
               t.amount_local, t.account_currency, t.amount_account, t.fx_rate_base,
               CASE WHEN t.account_currency = v_base THEN t.amount_account ELSE t.amount_base END AS row_base
        FROM ledger_transactions t
        WHERE t.portfolio_id = p_portfolio_id AND t.trade_date <= v_last
    ),
    -- Both legs of a conversion between own accounts carry the same booked amount in the same
    -- currency with opposite signs; value both at the base-currency leg when there is one.
    transfer_pairs AS (
        SELECT l.day, l.currency, ABS(l.amount_local) AS amount_abs,
               MAX(CASE WHEN l.account_currency = v_base THEN ABS(l.amount_account) END) AS base_leg
        FROM ledger l WHERE l.kind = 'transfer'
        GROUP BY l.day, l.currency, ABS(l.amount_local)
    ),
    valued AS (
        SELECT l.id, l.kind, l.day, l.security_id, l.quantity, l.price, l.currency, l.amount_local,
               l.account_currency, l.amount_account, l.fx_rate_base,
               COALESCE(
                   CASE WHEN l.kind = 'transfer' THEN SIGN(l.amount_local) * tp.base_leg END,
                   l.row_base, l.amount_account, 0
               ) AS row_base
        FROM ledger l
        LEFT JOIN transfer_pairs tp
               ON l.kind = 'transfer' AND tp.day = l.day AND tp.currency = l.currency
              AND tp.amount_abs = ABS(l.amount_local)
    ),
    ------------------------------------------------------------------------------------------
    -- Securities
    ------------------------------------------------------------------------------------------
    securities_held AS (
        SELECT s.id AS security_id,
               COALESCE(
                   s.currency,
                   (SELECT v.currency FROM valued v WHERE v.security_id = s.id ORDER BY v.day, v.id LIMIT 1),
                   v_base
               ) AS currency,
               MIN(v.day) AS first_day
        FROM valued v JOIN securities s ON s.id = v.security_id
        GROUP BY s.id, s.currency
    ),
    sec_events AS (
        SELECT v.security_id, v.day,
               SUM(CASE WHEN v.kind = 'trade' THEN v.quantity ELSE 0 END) AS trade_qty,
               -SUM(CASE WHEN v.kind = 'trade' THEN v.amount_local ELSE 0 END) AS trade_local,
               -SUM(CASE WHEN v.kind = 'trade' THEN v.row_base ELSE 0 END) AS trade_base,
               SUM(CASE WHEN v.kind = 'corporate_action' THEN v.quantity ELSE 0 END) AS ca_qty,
               SUM(CASE WHEN v.kind = 'corporate_action' AND v.quantity > 0
                        THEN v.quantity * COALESCE(v.price, 0) ELSE 0 END) AS ca_booked_value,
               (ARRAY_AGG(v.price ORDER BY v.quantity DESC) FILTER (WHERE v.kind = 'corporate_action'))[1]
                   AS ca_price,
               SUM(CASE WHEN v.kind IN ('dividend', 'lending_income') THEN v.row_base ELSE 0 END) AS dividend_base,
               SUM(CASE WHEN v.kind IN ('dividend', 'lending_income') AND v.currency = sh.currency
                        THEN v.amount_local ELSE 0 END) AS dividend_local_same,
               SUM(CASE WHEN v.kind IN ('dividend', 'lending_income') AND v.currency <> sh.currency
                        THEN v.row_base ELSE 0 END) AS dividend_base_other,
               SUM(CASE WHEN v.kind = 'interest' THEN v.row_base ELSE 0 END) AS interest_base,
               SUM(CASE WHEN v.kind IN ('commission', 'fee', 'tax', 'withholding_tax', 'other')
                        THEN v.row_base ELSE 0 END) AS cost_base,
               SUM(CASE WHEN v.kind IN ('commission', 'fee', 'tax', 'withholding_tax', 'other')
                         AND v.currency = sh.currency THEN v.amount_local ELSE 0 END) AS cost_local_same,
               SUM(CASE WHEN v.kind IN ('commission', 'fee', 'tax', 'withholding_tax', 'other')
                         AND v.currency <> sh.currency THEN v.row_base ELSE 0 END) AS cost_base_other
        FROM valued v JOIN securities_held sh ON sh.security_id = v.security_id
        GROUP BY v.security_id, v.day
    ),
    sec_grid AS (
        SELECT sh.security_id, sh.currency, d.day,
               COALESCE(e.trade_qty, 0) AS trade_qty,
               COALESCE(e.trade_local, 0) AS trade_local,
               COALESCE(e.trade_base, 0) AS trade_base,
               COALESCE(e.ca_qty, 0) AS ca_qty,
               COALESCE(e.ca_booked_value, 0) AS ca_booked_value,
               e.ca_price,
               COALESCE(e.dividend_base, 0) AS dividend_base,
               COALESCE(e.dividend_local_same, 0) AS dividend_local_same,
               COALESCE(e.dividend_base_other, 0) AS dividend_base_other,
               COALESCE(e.interest_base, 0) AS interest_base,
               COALESCE(e.cost_base, 0) AS cost_base,
               COALESCE(e.cost_local_same, 0) AS cost_local_same,
               COALESCE(e.cost_base_other, 0) AS cost_base_other,
               (e.security_id IS NOT NULL) AS has_event
        FROM securities_held sh
        JOIN days d ON d.day >= sh.first_day
        LEFT JOIN sec_events e ON e.security_id = sh.security_id AND e.day = d.day
    ),
    sec_running AS (
        SELECT g.*,
               SUM(g.trade_qty + g.ca_qty) OVER w - g.trade_qty - g.ca_qty AS qty_raw_before,
               SUM(g.trade_qty + g.ca_qty) OVER w AS qty_raw
        FROM sec_grid g
        WINDOW w AS (PARTITION BY g.security_id ORDER BY g.day)
    ),
    -- Corporate actions: a ratio change keeps the position (split), otherwise it opens or closes it.
    sec_ca AS (
        SELECT r.*,
               CASE
                   WHEN r.ca_qty = 0 THEN 'none'
                   WHEN r.qty_raw_before <> 0 AND r.qty_raw_before + r.ca_qty <> 0 THEN 'ratio'
                   WHEN r.qty_raw_before = 0 THEN 'enter'
                   ELSE 'leave'
               END AS ca_kind,
               CASE WHEN r.qty_raw_before <> 0 AND r.qty_raw_before + r.ca_qty <> 0
                    THEN (r.qty_raw_before + r.ca_qty) / r.qty_raw_before ELSE 1 END AS ratio
        FROM sec_running r
    ),
    -- factor(day) = product of the split ratios booked strictly after the day, which brings the
    -- raw quantity of that day onto the (split-adjusted) basis of the price history.
    sec_factor AS (
        SELECT c.*,
               numeric_product(c.ratio) OVER (PARTITION BY c.security_id)
                   / numeric_product(c.ratio) OVER (PARTITION BY c.security_id ORDER BY c.day) AS factor
        FROM sec_ca c
    ),
    -- Prices: the day's close, or the last close before (seeded on the first day), else the last
    -- ledger price (trade VWAP or corporate-action price) on the adjusted basis. The newer
    -- observation wins; a close beats a ledger price of the same day.
    sec_price_obs AS (
        SELECT f.security_id, f.day,
               CASE WHEN f.day = sh.first_day THEN seed.close ELSE p.close END AS close_obs,
               CASE WHEN f.day = sh.first_day THEN seed.price_date ELSE p.price_date END AS close_obs_date,
               CASE WHEN f.trade_qty <> 0 THEN f.trade_local / (f.trade_qty * f.factor)
                    WHEN f.ca_price IS NOT NULL AND f.ca_kind <> 'none' THEN f.ca_price / f.factor
               END AS ledger_obs
        FROM sec_factor f
        JOIN securities_held sh ON sh.security_id = f.security_id
        LEFT JOIN daily_prices p ON p.security_id = f.security_id AND p.price_date = f.day
        LEFT JOIN LATERAL (
            SELECT q.close, q.price_date FROM daily_prices q
            WHERE f.day = sh.first_day AND q.security_id = f.security_id AND q.price_date <= f.day
            ORDER BY q.price_date DESC LIMIT 1
        ) seed ON TRUE
    ),
    sec_price_groups AS (
        SELECT o.*,
               COUNT(o.close_obs) OVER w AS close_grp,
               COUNT(o.ledger_obs) OVER w AS ledger_grp
        FROM sec_price_obs o
        WINDOW w AS (PARTITION BY o.security_id ORDER BY o.day)
    ),
    sec_price AS (
        SELECT g.security_id, g.day,
               FIRST_VALUE(g.close_obs) OVER wc AS close_ff,
               FIRST_VALUE(g.close_obs_date) OVER wc AS close_date,
               FIRST_VALUE(g.ledger_obs) OVER wl AS ledger_ff,
               CASE WHEN FIRST_VALUE(g.ledger_obs) OVER wl IS NOT NULL THEN FIRST_VALUE(g.day) OVER wl END AS ledger_date
        FROM sec_price_groups g
        WINDOW wc AS (PARTITION BY g.security_id, g.close_grp ORDER BY g.day),
               wl AS (PARTITION BY g.security_id, g.ledger_grp ORDER BY g.day)
    ),
    -- Splits the ledger never booked (the position was closed before the split, or the broker
    -- booked nothing) show up as trade prices that are a multiple of the split-adjusted close.
    -- Infer the multiple on each trade day, snap it to a whole ratio, and carry it forward.
    sec_split_obs AS (
        SELECT sp.security_id, sp.day,
               CASE WHEN f.trade_qty <> 0 AND sp.ledger_date = sp.day AND sp.close_ff > 0 AND sp.ledger_ff > 0
                    THEN snap_split_ratio(sp.ledger_ff / sp.close_ff) END AS implied_obs
        FROM sec_price sp
        JOIN sec_factor f ON f.security_id = sp.security_id AND f.day = sp.day
    ),
    sec_split AS (
        SELECT o.security_id, o.day,
               COALESCE(FIRST_VALUE(o.implied_obs) OVER (PARTITION BY o.security_id, o.grp ORDER BY o.day), 1) AS inferred_split
        FROM (SELECT x.*, COUNT(x.implied_obs) OVER (PARTITION BY x.security_id ORDER BY x.day) AS grp FROM sec_split_obs x) o
    ),
    ------------------------------------------------------------------------------------------
    -- FX: base currency per unit of each currency in play, carried forward.
    ------------------------------------------------------------------------------------------
    currencies AS (
        SELECT sh.currency FROM securities_held sh
        UNION SELECT v.account_currency FROM valued v WHERE v.account_currency IS NOT NULL
        UNION SELECT v_base
    ),
    fx_obs AS (
        SELECT c.currency, d.day,
               CASE WHEN c.currency = v_base THEN 1
                    WHEN d.day = v_first THEN seed.rate ELSE f.rate END AS rate_obs,
               CASE WHEN c.currency = v_base THEN d.day
                    WHEN d.day = v_first THEN seed.rate_date ELSE f.rate_date END AS rate_obs_date
        FROM currencies c
        CROSS JOIN days d
        LEFT JOIN fx_rates f ON f.base_currency = v_base AND f.currency = c.currency AND f.rate_date = d.day
        LEFT JOIN LATERAL (
            SELECT q.rate, q.rate_date FROM fx_rates q
            WHERE d.day = v_first AND c.currency <> v_base
              AND q.base_currency = v_base AND q.currency = c.currency AND q.rate_date <= d.day
            ORDER BY q.rate_date DESC LIMIT 1
        ) seed ON TRUE
    ),
    fx_groups AS (
        SELECT o.*, COUNT(o.rate_obs) OVER (PARTITION BY o.currency ORDER BY o.day) AS grp FROM fx_obs o
    ),
    fx AS (
        SELECT g.currency, g.day,
               FIRST_VALUE(g.rate_obs) OVER w AS rate,
               FIRST_VALUE(g.rate_obs_date) OVER w AS rate_date
        FROM fx_groups g
        WINDOW w AS (PARTITION BY g.currency, g.grp ORDER BY g.day)
    ),
    ------------------------------------------------------------------------------------------
    -- Security position days, stage A: quantities, carried prices and FX, prior values.
    ------------------------------------------------------------------------------------------
    sec_a AS (
        SELECT f.security_id, f.currency, f.day, f.has_event, f.ca_kind, f.ca_booked_value,
               f.factor * ss.inferred_split AS basis_factor,
               ss.inferred_split,
               f.qty_raw * f.factor * ss.inferred_split AS qty,
               f.trade_qty * f.factor * ss.inferred_split AS trade_qty_adj,
               CASE WHEN f.ca_kind IN ('enter', 'leave') THEN f.ca_qty * f.factor * ss.inferred_split ELSE 0 END AS ca_qty_adj,
               f.trade_local, f.trade_base,
               f.dividend_base, f.dividend_local_same, f.dividend_base_other, f.interest_base,
               f.cost_base, f.cost_local_same, f.cost_base_other,
               CASE WHEN sp.ledger_date IS NOT NULL AND (sp.close_date IS NULL OR sp.ledger_date > sp.close_date)
                    THEN sp.ledger_ff / ss.inferred_split ELSE sp.close_ff END AS price,
               CASE WHEN sp.ledger_date IS NOT NULL AND (sp.close_date IS NULL OR sp.ledger_date > sp.close_date)
                    THEN sp.ledger_date ELSE sp.close_date END AS price_date,
               CASE WHEN sp.ledger_date IS NOT NULL AND (sp.close_date IS NULL OR sp.ledger_date > sp.close_date)
                    THEN 'ledger' WHEN sp.close_ff IS NOT NULL THEN 'close' END AS price_source,
               x.rate AS fx, x.rate_date AS fx_date
        FROM sec_factor f
        JOIN sec_price sp ON sp.security_id = f.security_id AND sp.day = f.day
        JOIN sec_split ss ON ss.security_id = f.security_id AND ss.day = f.day
        LEFT JOIN fx x ON x.currency = f.currency AND x.day = f.day
    ),
    -- Prior values are the previous row's effective values (a missing price counted as 0 and a
    -- missing FX as 1), so prev_market_value equals yesterday's stored market value exactly.
    sec_b AS (
        SELECT a.*,
               COALESCE(LAG(a.qty) OVER w, 0) AS qty_prev,
               COALESCE(LAG(COALESCE(a.price, 0)) OVER w, a.price, 0) AS price_prev,
               COALESCE(LAG(COALESCE(a.fx, 1)) OVER w, a.fx, 1) AS fx_prev,
               COALESCE(a.price, 0) AS price_now,
               COALESCE(a.fx, 1) AS fx_now,
               ROUND(COALESCE(LAG(a.qty) OVER w, 0) * COALESCE(LAG(COALESCE(a.price, 0)) OVER w, a.price, 0)
                     * COALESCE(LAG(COALESCE(a.fx, 1)) OVER w, a.fx, 1), 8) AS carried_value
        FROM sec_a a
        WINDOW w AS (PARTITION BY a.security_id ORDER BY a.day)
    ),
    -- Corporate actions that replace one security by another: the leaving side hands its carried
    -- value to the entering side(s) of the same day, pro rata to the booked value. Rounded so the
    -- shares add up exactly.
    ca_transfer AS (
        SELECT b.day,
               SUM(CASE WHEN b.ca_kind = 'leave' THEN b.carried_value ELSE 0 END) AS leaving_value,
               SUM(CASE WHEN b.ca_kind = 'enter' THEN b.ca_booked_value ELSE 0 END) AS entering_booked,
               COUNT(*) FILTER (WHERE b.ca_kind = 'enter') AS entering_legs
        FROM sec_b b WHERE b.ca_kind IN ('enter', 'leave')
        GROUP BY b.day
    ),
    ca_alloc AS (
        SELECT b.security_id, b.day,
               CASE WHEN ct.entering_legs = 0 THEN 0
                    WHEN ct.entering_booked > 0 THEN ROUND(ct.leaving_value * b.ca_booked_value / ct.entering_booked, 8)
                    ELSE ROUND(ct.leaving_value / ct.entering_legs, 8) END AS entering_value,
               ROW_NUMBER() OVER (PARTITION BY b.day ORDER BY b.ca_booked_value DESC, b.security_id) AS leg_no,
               ct.leaving_value, ct.entering_legs
        FROM sec_b b JOIN ca_transfer ct ON ct.day = b.day
        WHERE b.ca_kind = 'enter'
    ),
    ca_alloc_exact AS (
        SELECT a.security_id, a.day,
               CASE WHEN a.leg_no = 1
                    THEN a.leaving_value - COALESCE(SUM(a.entering_value) OVER (PARTITION BY a.day) - a.entering_value, 0)
                    ELSE a.entering_value END AS entering_value
        FROM ca_alloc a
    ),
    sec_c AS (
        SELECT b.*,
               b.trade_qty_adj + b.ca_qty_adj AS dq,
               -- trades plus corporate-action legs valued as trades: leaving at the carried value,
               -- entering at the value received (converted to local at today's FX)
               b.trade_local
                   + CASE WHEN b.ca_kind = 'leave' AND ct.entering_legs > 0 THEN b.ca_qty_adj * b.price_prev ELSE 0 END
                   + CASE WHEN b.ca_kind = 'enter' AND ct.entering_legs > 0
                          THEN ROUND(COALESCE(al.entering_value, 0) / b.fx_now, 8) ELSE 0 END AS trade_local_all,
               b.trade_base
                   + CASE WHEN b.ca_kind = 'leave' AND ct.entering_legs > 0 THEN -b.carried_value ELSE 0 END
                   + CASE WHEN b.ca_kind = 'enter' THEN COALESCE(al.entering_value, 0) ELSE 0 END AS trade_base_all
        FROM sec_b b
        LEFT JOIN ca_transfer ct ON ct.day = b.day AND b.ca_kind IN ('enter', 'leave')
        LEFT JOIN ca_alloc_exact al ON al.security_id = b.security_id AND al.day = b.day
    ),
    sec_d AS (
        SELECT c.security_id, c.currency, c.day, c.has_event,
               c.qty_prev, c.qty, c.dq, c.basis_factor, c.inferred_split,
               c.price_prev, c.price, c.price_date, c.price_source, c.price_now,
               c.fx_prev, c.fx, c.fx_date, c.fx_now,
               CASE WHEN c.dq <> 0 THEN c.trade_local_all / c.dq END AS execution_price,
               CASE WHEN c.trade_local_all <> 0 THEN c.trade_base_all / c.trade_local_all ELSE c.fx_now END AS execution_fx,
               ROUND(c.qty * c.price_now, 8) AS mv_local,
               ROUND(c.qty * c.price_now * c.fx_now, 8) AS mv_base,
               c.carried_value AS mv_base_prev,
               ROUND(c.trade_local_all, 8) AS trade_local,
               ROUND(c.trade_base_all, 8) AS trade_base,
               ROUND(c.qty_prev * (c.price_now - c.price_prev) * c.fx_prev
                     + c.dq * c.price_now
                       * CASE WHEN c.trade_local_all <> 0 THEN c.trade_base_all / c.trade_local_all ELSE c.fx_now END
                     - c.trade_base_all, 8) AS price_effect_base,
               ROUND(c.qty_prev * (c.price_now - c.price_prev) + c.dq * c.price_now - c.trade_local_all, 8) AS price_effect_local,
               ROUND(c.qty_prev * c.price_prev * (c.fx_now - c.fx_prev) + c.trade_local_all * c.fx_now - c.trade_base_all, 8)
                   AS fx_effect_base,
               c.dividend_base,
               ROUND(c.dividend_local_same + c.dividend_base_other / c.fx_now, 8) AS dividend_local,
               c.interest_base,
               c.cost_base,
               ROUND(c.cost_local_same + c.cost_base_other / c.fx_now, 8) AS cost_local
        FROM sec_c c
    ),
    sec_rows AS (
        SELECT 'security' AS position_kind, d.security_id, 'sec:' || d.security_id AS position_key,
               d.currency, d.day, d.has_event,
               d.qty_prev, d.qty, d.dq AS trade_quantity, d.basis_factor, d.inferred_split,
               d.price_prev, d.price, d.price_date, d.price_source,
               d.fx_prev, d.fx, d.fx_date, d.execution_price, d.execution_fx,
               d.mv_local, d.mv_base, d.mv_base_prev,
               d.trade_local, d.trade_base,
               d.price_effect_base, d.price_effect_local, d.fx_effect_base,
               d.mv_base - d.mv_base_prev - d.trade_base - d.price_effect_base - d.fx_effect_base AS interaction_effect_base,
               d.dividend_base, d.dividend_local, d.interest_base, d.cost_base, d.cost_local,
               d.price_effect_local + d.dividend_local + ROUND(d.interest_base / d.fx_now, 8) + d.cost_local AS daily_pnl_local
        FROM sec_d d
    ),
    ------------------------------------------------------------------------------------------
    -- Cash per currency
    ------------------------------------------------------------------------------------------
    cash_events AS (
        SELECT v.account_currency AS currency, v.day,
               SUM(v.amount_account) AS delta,
               SUM(CASE WHEN v.security_id IS NOT NULL OR v.kind IN ('deposit', 'withdrawal', 'transfer')
                        THEN v.amount_account ELSE 0 END) AS flow_local,
               SUM(CASE WHEN v.security_id IS NOT NULL OR v.kind IN ('deposit', 'withdrawal', 'transfer')
                        THEN v.row_base ELSE 0 END) AS flow_base,
               SUM(CASE WHEN v.security_id IS NULL AND v.kind IN ('dividend', 'lending_income')
                        THEN v.row_base ELSE 0 END) AS dividend_base,
               SUM(CASE WHEN v.security_id IS NULL AND v.kind IN ('dividend', 'lending_income')
                        THEN v.amount_account ELSE 0 END) AS dividend_local,
               SUM(CASE WHEN v.security_id IS NULL AND v.kind = 'interest' THEN v.row_base ELSE 0 END) AS interest_base,
               SUM(CASE WHEN v.security_id IS NULL AND v.kind IN ('commission', 'fee', 'tax', 'withholding_tax', 'other')
                        THEN v.row_base ELSE 0 END) AS cost_base,
               SUM(CASE WHEN v.security_id IS NULL AND v.kind IN ('commission', 'fee', 'tax', 'withholding_tax', 'other')
                        THEN v.amount_account ELSE 0 END) AS cost_local
        FROM valued v
        WHERE v.account_currency IS NOT NULL AND v.amount_account IS NOT NULL
        GROUP BY v.account_currency, v.day
    ),
    -- Whatever a day's transfer legs do not net to (conversions between two foreign accounts,
    -- unpaired legs) is a conversion cost on the base-currency cash, not an external flow.
    transfer_residual AS (
        SELECT v.day, SUM(v.row_base) AS residual FROM valued v WHERE v.kind = 'transfer'
        GROUP BY v.day HAVING SUM(v.row_base) <> 0
    ),
    cash_currencies AS (
        SELECT c.currency, MIN(c.day) AS first_day FROM cash_events c GROUP BY c.currency
        UNION ALL
        SELECT v_base, v_first WHERE NOT EXISTS (SELECT 1 FROM cash_events c WHERE c.currency = v_base)
    ),
    cash_grid AS (
        SELECT cc.currency, d.day,
               COALESCE(e.delta, 0) AS delta,
               COALESCE(e.flow_local, 0) AS flow_local,
               COALESCE(e.flow_base, 0) - CASE WHEN cc.currency = v_base THEN COALESCE(tr.residual, 0) ELSE 0 END AS flow_base,
               COALESCE(e.dividend_base, 0) AS dividend_base,
               COALESCE(e.dividend_local, 0) AS dividend_local,
               COALESCE(e.interest_base, 0) AS interest_base,
               COALESCE(e.cost_base, 0) + CASE WHEN cc.currency = v_base THEN COALESCE(tr.residual, 0) ELSE 0 END AS cost_base,
               COALESCE(e.cost_local, 0) + CASE WHEN cc.currency = v_base THEN COALESCE(tr.residual, 0) ELSE 0 END AS cost_local,
               (e.currency IS NOT NULL OR (cc.currency = v_base AND tr.day IS NOT NULL)) AS has_event
        FROM cash_currencies cc
        JOIN days d ON d.day >= cc.first_day
        LEFT JOIN cash_events e ON e.currency = cc.currency AND e.day = d.day
        LEFT JOIN transfer_residual tr ON tr.day = d.day
    ),
    cash_a AS (
        SELECT g.*, SUM(g.delta) OVER w AS qty, SUM(g.delta) OVER w - g.delta AS qty_prev,
               x.rate AS fx, x.rate_date AS fx_date
        FROM cash_grid g LEFT JOIN fx x ON x.currency = g.currency AND x.day = g.day
        WINDOW w AS (PARTITION BY g.currency ORDER BY g.day)
    ),
    cash_b AS (
        SELECT a.*,
               COALESCE(LAG(COALESCE(a.fx, 1)) OVER w, a.fx, 1) AS fx_prev,
               COALESCE(a.fx, 1) AS fx_now,
               ROUND(a.qty * COALESCE(a.fx, 1), 8) AS mv_base,
               ROUND(a.qty_prev * COALESCE(LAG(COALESCE(a.fx, 1)) OVER w, a.fx, 1), 8) AS mv_base_prev
        FROM cash_a a
        WINDOW w AS (PARTITION BY a.currency ORDER BY a.day)
    ),
    cash_rows AS (
        SELECT 'cash' AS position_kind, NULL::bigint AS security_id, 'cash:' || b.currency AS position_key,
               b.currency, b.day, b.has_event,
               b.qty_prev, b.qty, b.flow_local AS trade_quantity, 1::numeric AS basis_factor, 1::numeric AS inferred_split,
               1::numeric AS price_prev, 1::numeric AS price, b.day AS price_date, 'cash'::text AS price_source,
               b.fx_prev, b.fx, b.fx_date,
               1::numeric AS execution_price,
               CASE WHEN b.flow_local <> 0 THEN b.flow_base / b.flow_local ELSE b.fx_now END AS execution_fx,
               ROUND(b.qty, 8) AS mv_local, b.mv_base, b.mv_base_prev,
               ROUND(b.flow_local, 8) AS trade_local, ROUND(b.flow_base, 8) AS trade_base,
               0::numeric AS price_effect_base, 0::numeric AS price_effect_local,
               b.mv_base - b.mv_base_prev - ROUND(b.flow_base, 8) - b.dividend_base - b.interest_base - b.cost_base AS fx_effect_base,
               0::numeric AS interaction_effect_base,
               b.dividend_base, ROUND(b.dividend_local, 8) AS dividend_local, b.interest_base, b.cost_base,
               ROUND(b.cost_local, 8) AS cost_local,
               ROUND(b.qty - b.qty_prev - b.flow_local, 8) AS daily_pnl_local
        FROM cash_b b
    ),
    ------------------------------------------------------------------------------------------
    -- Union, filter to days that matter, derive returns and running totals.
    ------------------------------------------------------------------------------------------
    all_rows AS (
        SELECT * FROM sec_rows UNION ALL SELECT * FROM cash_rows
    ),
    kept AS (
        SELECT r.*,
               r.price_effect_base + r.fx_effect_base + r.interaction_effect_base
                   + r.dividend_base + r.interest_base + r.cost_base AS daily_pnl_base
        FROM all_rows r
        WHERE r.qty_prev <> 0 OR r.qty <> 0 OR r.has_event
    )
    SELECT p_portfolio_id, k.position_key, k.day, k.position_kind, k.security_id, k.currency, v_base,
           k.qty_prev, k.qty, k.trade_quantity, k.basis_factor, k.inferred_split,
           k.price_prev, k.price, k.price_date, k.price_source, k.fx_prev, k.fx, k.fx_date,
           k.execution_price, k.execution_fx,
           k.mv_local, k.mv_base, k.mv_base_prev,
           k.trade_local, k.trade_base,
           -- income and costs leave a security position for cash, but stay inside a cash position
           CASE WHEN k.position_kind = 'security' THEN k.trade_base - k.dividend_base - k.interest_base - k.cost_base
                ELSE k.trade_base END AS flow_base,
           k.price_effect_base, k.price_effect_local, k.fx_effect_base, k.interaction_effect_base,
           k.dividend_base, k.dividend_local, k.interest_base, k.cost_base, k.cost_local,
           k.daily_pnl_base, k.daily_pnl_local,
           CASE WHEN k.mv_base_prev <> 0 THEN k.daily_pnl_base / ABS(k.mv_base_prev)
                WHEN k.trade_base <> 0 THEN k.daily_pnl_base / ABS(k.trade_base) END AS daily_return_pct,
           CASE WHEN k.mv_base_prev <> 0 THEN k.daily_pnl_local * COALESCE(k.fx_prev, 1) / ABS(k.mv_base_prev)
                WHEN k.trade_base <> 0 THEN k.daily_pnl_local * COALESCE(k.execution_fx, 1) / ABS(k.trade_base) END
               AS constant_currency_return_pct,
           SUM(k.daily_pnl_base) OVER (PARTITION BY k.position_key ORDER BY k.day) AS total_pnl_base,
           SUM(k.daily_pnl_local) OVER (PARTITION BY k.position_key ORDER BY k.day) AS total_pnl_local
    FROM kept k;
    GET DIAGNOSTICS v_position_rows = ROW_COUNT;

    ------------------------------------------------------------------------------------------
    -- Portfolio days: NAV, external flows, unitized return (VISION 4.1).
    ------------------------------------------------------------------------------------------
    INSERT INTO portfolio_days (
        portfolio_id, day, base_currency, nav, positions_value, cash_value, nav_prev, flow, daily_pnl,
        daily_return_pct, unit_price, units, cumulative_return_pct, drawdown_pct, broker_value,
        broker_cash_value, gap_fx, gap_cash, gap_securities
    )
    WITH days AS (
        SELECT d::date AS day FROM generate_series(v_first, v_last, interval '1 day') AS d
    ),
    valuation AS (
        SELECT d.day,
               COALESCE(SUM(p.market_value_base), 0) AS nav,
               COALESCE(SUM(p.market_value_base) FILTER (WHERE p.position_kind = 'security'), 0) AS positions_value,
               COALESCE(SUM(p.market_value_base) FILTER (WHERE p.position_kind = 'cash'), 0) AS cash_value,
               COALESCE(SUM(p.daily_pnl_base), 0) AS daily_pnl
        FROM days d
        LEFT JOIN pnl_days p ON p.portfolio_id = p_portfolio_id AND p.day = d.day
        GROUP BY d.day
    ),
    flows AS (
        SELECT t.trade_date AS day,
               SUM(CASE WHEN t.account_currency = v_base THEN t.amount_account ELSE t.amount_base END) AS flow
        FROM ledger_transactions t
        WHERE t.portfolio_id = p_portfolio_id AND t.kind IN ('deposit', 'withdrawal') AND t.trade_date <= v_last
        GROUP BY t.trade_date
    ),
    broker AS (
        SELECT DISTINCT ON (cs.snapshot_date) cs.snapshot_date AS day, cs.total_value, cs.cash_balance
        FROM cash_snapshots cs
        WHERE cs.portfolio_id = p_portfolio_id AND cs.account_key = '' AND cs.currency = v_base
        ORDER BY cs.snapshot_date, cs.fetched_at DESC
    ),
    -- The engine's holdings revalued at the broker's own FX rates (last rate on or before the day),
    -- on broker-value days. Complete only when every held currency has a broker rate; then
    -- nav - broker_value splits exactly into FX, cash and securities (see the final SELECT).
    at_broker_fx AS (
        SELECT p.day,
               COALESCE(SUM(p.market_value_local * r.rate) FILTER (WHERE p.position_kind = 'cash'), 0) AS cash_value,
               COALESCE(SUM(p.market_value_local * r.rate) FILTER (WHERE p.position_kind = 'security'), 0)
                   AS securities_value,
               BOOL_AND(r.rate IS NOT NULL) AS complete
        FROM pnl_days p
        JOIN broker b ON b.day = p.day
        LEFT JOIN LATERAL broker_fx_rate_on(p_portfolio_id, p.currency, p.day) r ON TRUE
        WHERE p.portfolio_id = p_portfolio_id AND p.market_value_local <> 0
        GROUP BY p.day
    ),
    series AS (
        SELECT v.day, v.nav, v.positions_value, v.cash_value, v.daily_pnl,
               COALESCE(LAG(v.nav) OVER (ORDER BY v.day), 0) AS nav_prev,
               COALESCE(f.flow, 0) AS flow,
               CASE WHEN COALESCE(LAG(v.nav) OVER (ORDER BY v.day), 0) > 0
                    THEN (v.nav - COALESCE(f.flow, 0)) / LAG(v.nav) OVER (ORDER BY v.day) - 1 END AS r
        FROM valuation v LEFT JOIN flows f ON f.day = v.day
    ),
    unitized AS (
        SELECT s.*, 100 * numeric_product(1 + COALESCE(s.r, 0)) OVER (ORDER BY s.day) AS unit_price
        FROM series s
    )
    SELECT p_portfolio_id, u.day, v_base, u.nav, u.positions_value, u.cash_value, u.nav_prev, u.flow, u.daily_pnl,
           u.r, u.unit_price,
           CASE WHEN u.unit_price > 0 THEN u.nav / u.unit_price ELSE 0 END,
           u.unit_price / 100 - 1,
           u.unit_price / MAX(u.unit_price) OVER (ORDER BY u.day) - 1,
           b.total_value,
           b.cash_balance,
           CASE WHEN x.complete AND b.cash_balance IS NOT NULL
                THEN u.nav - x.cash_value - x.securities_value END,
           CASE WHEN x.complete AND b.cash_balance IS NOT NULL THEN x.cash_value - b.cash_balance END,
           CASE WHEN x.complete AND b.cash_balance IS NOT NULL
                THEN x.securities_value - (b.total_value - b.cash_balance) END
    FROM unitized u
    LEFT JOIN broker b ON b.day = u.day
    LEFT JOIN at_broker_fx x ON x.day = u.day
    ORDER BY u.day;
    GET DIAGNOSTICS v_portfolio_rows = ROW_COUNT;

    ------------------------------------------------------------------------------------------
    -- Issues: what the numbers above had to assume.
    ------------------------------------------------------------------------------------------
    INSERT INTO reconciliation_issues (portfolio_id, day, kind, security_id, currency, amount, message)
    SELECT p_portfolio_id, MAX(p.day), 'missing_price', p.security_id, p.currency, NULL::numeric,
           'no price on ' || COUNT(*) || ' held day(s) between ' || MIN(p.day) || ' and ' || MAX(p.day)
           || '; the position is carried at zero'
    FROM pnl_days p
    WHERE p.portfolio_id = p_portfolio_id AND p.position_kind = 'security' AND p.price IS NULL AND p.quantity <> 0
    GROUP BY p.security_id, p.currency
    UNION ALL
    SELECT p_portfolio_id, MAX(p.day), 'stale_price', p.security_id, p.currency, NULL::numeric,
           'price carried more than 7 days on ' || COUNT(*) || ' held day(s), last on ' || MAX(p.day)
           || ' (' || MAX(p.price_source) || ' of ' || MIN(p.price_date) || ')'
    FROM pnl_days p
    WHERE p.portfolio_id = p_portfolio_id AND p.position_kind = 'security' AND p.price IS NOT NULL
      AND p.quantity <> 0 AND p.price_date < p.day - 7
    GROUP BY p.security_id, p.currency
    UNION ALL
    SELECT p_portfolio_id, MAX(p.day), 'missing_fx', NULL::bigint, p.currency, NULL::numeric,
           'no FX rate for ' || p.currency || ' on ' || COUNT(*) || ' day(s) between ' || MIN(p.day) || ' and '
           || MAX(p.day) || '; valued at 1'
    FROM pnl_days p
    WHERE p.portfolio_id = p_portfolio_id AND p.fx IS NULL AND (p.quantity <> 0 OR p.quantity_prev <> 0)
    GROUP BY p.currency
    UNION ALL
    SELECT p_portfolio_id, MIN(p.day), 'inferred_split', p.security_id, p.currency, p.inferred_split,
           'quantities from ' || MIN(p.day) || ' scaled by ' || p.inferred_split::text
           || ' to match the split-adjusted price history (inferred from trade prices vs closes)'
    FROM pnl_days p
    WHERE p.portfolio_id = p_portfolio_id AND p.position_kind = 'security' AND p.inferred_split <> 1
    GROUP BY p.security_id, p.currency, p.inferred_split
    UNION ALL
    SELECT p_portfolio_id, d.day, 'nav_mismatch', NULL::bigint, v_base, d.nav - d.broker_value,
           -- A percentage, not the two values: the message is shown as is, also with amounts hidden.
           CASE WHEN d.broker_value = 0 THEN 'engine NAV is not zero, but the broker reports an account value of zero'
                ELSE 'engine NAV differs from the broker''s account value by '
                     || ROUND(100 * (d.nav - d.broker_value) / ABS(d.broker_value), 2) || '%'
           END
    FROM portfolio_days d
    -- 0.5% tolerance: closes from the price source and the broker's own marks are taken at
    -- different times (a European product on a US index, marked after the US session, can move
    -- several percent), and those timing gaps reverse the next day; anything larger is worth a look.
    WHERE d.portfolio_id = p_portfolio_id AND d.broker_value IS NOT NULL
      AND ABS(d.nav - d.broker_value) > GREATEST(ABS(d.broker_value) * 0.005, 1);
    GET DIAGNOSTICS v_issue_rows = ROW_COUNT;

    RETURN QUERY SELECT v_position_rows, v_portfolio_rows, v_issue_rows;
END;
$$;
