"""The SQL PnL engine against real PostgreSQL; needs TEST_DATABASE_URL.

The fixture is a small ledger over eight calendar days (2024-01-02 to 2024-01-09, with a weekend on
the 6th and 7th) that exercises: a deposit, a buy with commission on an FX move, a price-and-FX day,
carried values over the weekend, a dividend with withholding tax on a deposit day, a sale, a booked
2:1 split, a split the ledger never booked, a short position, and a DKK-to-USD conversion between
own accounts. Expected numbers are worked by hand from documentation/VISION.md 4.1 and 4.2.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app import db
from app.routes.reports import DashboardResponse
from app.services import dashboard_service, pnl_service
from app.services.ledger_queries import Page

D = Decimal
JAN = {day: date(2024, 1, day) for day in range(2, 10)}


def close(left: Any, right: Any, places: int = 9) -> bool:
    """Stored ratios are rounded to 12 decimals; compare against exact fractions with a small tolerance."""
    return abs(D(left) - D(right)) < D(10) ** -places


@pytest.fixture
def engine_db(migrated_db: None) -> Iterator[None]:
    _load_fixture()
    yield


# --- fixture -------------------------------------------------------------------------------------


def _load_fixture() -> None:
    db.execute(
        "INSERT INTO broker_connections (broker, environment, access_token_encrypted, access_token_expires_at)"
        " VALUES ('saxo', 'sim', 'x', CURRENT_TIMESTAMP)"
    )
    db.execute("INSERT INTO portfolios (connection_id, name, base_currency) VALUES (1, 'Test', 'DKK')")
    for uic, ticker, currency in ((1, "AAA", "USD"), (2, "BBB", "USD"), (3, "CCC", "USD"), (4, "DDD", "USD")):
        db.execute(
            "INSERT INTO securities (broker, uic, asset_type, symbol, ticker, mic, name, currency, raw)"
            " VALUES ('saxo', %s, 'Stock', %s, %s, 'XNAS', %s, %s, '{}')",
            (uic, f"{ticker}:xnas", ticker, f"{ticker} Inc", currency),
        )
    closes = {
        1: {2: "99", 3: "102", 4: "101", 5: "101", 8: "101", 9: "104"},  # AAA
        2: {2: "100", 3: "100", 4: "101", 5: "101", 8: "101", 9: "101"},  # BBB, split-adjusted (2:1 on the 4th)
        3: {2: "150", 3: "150", 4: "150", 5: "150", 8: "150", 9: "150"},  # CCC, adjusted for a split never booked
        4: {2: "50", 3: "48", 4: "48", 5: "48", 8: "48", 9: "48"},  # DDD
    }
    for security_id, series in closes.items():
        for day, close in series.items():
            db.execute(
                "INSERT INTO daily_prices (security_id, price_date, close, currency, source)"
                " VALUES (%s, %s, %s, 'USD', 'saxo')",
                (security_id, JAN[day], D(close)),
            )
    for day, rate in {2: "6.90", 3: "6.95", 4: "7.00", 5: "7.00", 8: "7.00", 9: "7.05"}.items():
        db.execute(
            "INSERT INTO fx_rates (rate_date, base_currency, currency, rate, source)"
            " VALUES (%s, 'DKK', 'USD', %s, 'ecb'),"
            " (%s, 'DKK', 'DKK', 1, 'identity')",
            (JAN[day], D(rate), JAN[day]),
        )

    rows: list[dict[str, Any]] = []

    def add(kind: str, day: int, **fields: Any) -> None:
        row = {
            "kind": kind,
            "trade_date": JAN[day],
            "security_id": None,
            "quantity": None,
            "price": None,
            "currency": "DKK",
            "amount_local": D(0),
            "account_currency": "DKK",
            "amount_account": None,
            "amount_base": None,
            "fx_rate_base": None,
            "related_ref": None,
            "description": kind,
        }
        row.update(fields)
        if row["amount_account"] is None:
            row["amount_account"] = row["amount_local"]
        if row["amount_base"] is None:
            row["amount_base"] = row["amount_account"] if row["account_currency"] == "DKK" else row["amount_local"]
        rows.append(row)

    add("deposit", 2, amount_local=D(10000))
    # AAA: buy 10 @ 100 USD at 6.90, commission 3 USD; sell 10 @ 105 USD at 7.10 on the 9th
    add(
        "trade",
        3,
        security_id=1,
        quantity=D(10),
        price=D(100),
        currency="USD",
        amount_local=D(-1000),
        amount_account=D(-6900),
    )
    add(
        "commission", 3, security_id=1, currency="USD", amount_local=D(-3), amount_account=D("-20.70"), related_ref="t1"
    )
    add("dividend", 8, security_id=1, currency="USD", amount_local=D(5), amount_account=D(35))
    add("withholding_tax", 8, security_id=1, currency="USD", amount_local=D("-0.75"), amount_account=D("-5.25"))
    add("deposit", 8, amount_local=D(1000))
    add(
        "trade",
        9,
        security_id=1,
        quantity=D(-10),
        price=D(105),
        currency="USD",
        amount_local=D(1050),
        amount_account=D(7455),
    )
    # BBB: buy 4 @ 200 on the 3rd, booked 2:1 split on the 4th (sell-all plus buy at zero cash)
    add(
        "trade",
        3,
        security_id=2,
        quantity=D(4),
        price=D(200),
        currency="USD",
        amount_local=D(-800),
        amount_account=D(-5520),
    )
    add(
        "corporate_action",
        4,
        security_id=2,
        quantity=D(-4),
        price=D(200),
        currency="USD",
        amount_local=D(0),
        amount_account=D(0),
    )
    add(
        "corporate_action",
        4,
        security_id=2,
        quantity=D(8),
        price=D(100),
        currency="USD",
        amount_local=D(0),
        amount_account=D(0),
    )
    # CCC: buy 2 @ 300 on the 3rd while the price history is already adjusted for a later 2:1 split
    add(
        "trade",
        3,
        security_id=3,
        quantity=D(2),
        price=D(300),
        currency="USD",
        amount_local=D(-600),
        amount_account=D(-4140),
    )
    # DDD: short 3 @ 50 on the 3rd
    add(
        "trade",
        3,
        security_id=4,
        quantity=D(-3),
        price=D(50),
        currency="USD",
        amount_local=D(150),
        amount_account=D(1035),
    )
    # Conversion on the 8th: 700 DKK out of the DKK account, 100 USD into the USD account. Saxo values
    # the USD leg at 698 DKK in client currency; both legs must be valued at the exact 700.
    add("transfer", 8, amount_local=D(-700), amount_account=D(-700), related_ref="c1")
    add(
        "transfer",
        8,
        amount_local=D(700),
        account_currency="USD",
        amount_account=D(100),
        amount_base=D(698),
        related_ref="c2",
    )

    for index, row in enumerate(rows):
        db.execute(
            """
            INSERT INTO ledger_transactions (connection_id, portfolio_id, broker_ref, kind, trade_date, security_id,
                quantity, price, currency, amount_local, account_currency, amount_account, base_currency, amount_base,
                fx_rate_base, related_ref, description, source_endpoint, raw)
            VALUES (1, 1, %(ref)s, %(kind)s, %(trade_date)s, %(security_id)s, %(quantity)s, %(price)s, %(currency)s,
                %(amount_local)s, %(account_currency)s, %(amount_account)s, 'DKK', %(amount_base)s, %(fx_rate_base)s,
                %(related_ref)s, %(description)s, 'test', '{}')
            """,
            {**row, "ref": f"ref-{index}"},
        )


def _rows(position_key: str) -> dict[date, dict[str, Any]]:
    rows = db.select("SELECT * FROM pnl_days WHERE position_key = %s ORDER BY day", (position_key,))
    return {row["day"]: row for row in rows}


def _rebuild() -> dict[str, Any]:
    return pnl_service.rebuild(1, through=JAN[9])


# --- tests ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("through", [JAN[3], JAN[8], JAN[9]])
def test_dashboard_matches_accounting_and_includes_cash_fx(engine_db: None, through: date) -> None:
    pnl_service.rebuild(1, through=through)
    result = DashboardResponse.model_validate(dashboard_service.dashboard())
    day = pnl_service.portfolio_days(1)[-1]
    assert result.as_of == through
    assert result.base_currency == "DKK"
    assert result.nav == day["nav"] == result.series[-1].nav
    assert result.daily_pnl == day["daily_pnl"]
    assert close(result.daily_return_pct, day["daily_return_pct"])
    assert result.issue_count == len(pnl_service.list_issues())
    rows, count = pnl_service.list_pnl_rows(
        pnl_service.PnlFilter(date_gte=through, date_lte=through),
        Page(page=1, per_page=1000, order_by="day", order="desc"),
    )
    assert count >= 5
    assert result.fx_effect_base == sum(row["fx_effect_base"] for row in rows)
    values = sorted(row["daily_pnl_base"] for row in rows)
    assert [row.daily_pnl_base for row in result.top] == list(reversed(values[-5:]))
    assert [row.daily_pnl_base for row in result.bottom] == values[:5]
    if through == JAN[9]:
        assert any(row.position_kind == "cash" and row.currency == "USD" for row in result.top)
        assert result.fx_effect_base == D(5) + sum(
            row["fx_effect_base"] for row in rows if row["position_kind"] == "security"
        )


def test_dashboard_empty_results_are_missing_not_zero(engine_db: None) -> None:
    result = DashboardResponse.model_validate(dashboard_service.dashboard())
    assert result.as_of is None
    assert result.nav is None and result.daily_pnl is None and result.fx_effect_base is None
    assert not result.series and not result.top and not result.bottom
    assert result.portfolios[0].nav is None
    assert "excluded from totals" in result.warnings[0]


@pytest.mark.parametrize(
    ("through", "expected"),
    [(JAN[5], JAN[5]), (JAN[7], JAN[5]), (date(2024, 1, 12), JAN[9])],
)
def test_dashboard_uses_observation_dates_not_nonzero_returns(engine_db: None, through: date, expected: date) -> None:
    pnl_service.rebuild(1, through=through)
    result = DashboardResponse.model_validate(dashboard_service.dashboard())
    assert result.as_of == expected
    assert result.series[-1].day == expected
    assert all(row.day == expected for row in result.top + result.bottom)
    day = pnl_service.portfolio_days(1, date_lte=expected)[-1]
    assert result.nav == day["nav"]
    assert result.daily_pnl == day["daily_pnl"]
    assert any("pending" in warning for warning in result.warnings) == (through > expected)
    if expected == JAN[5]:
        # The Friday has genuine unchanged prices and FX: do not go back to a profitable day.
        assert result.daily_pnl == 0


def test_dashboard_accepts_foreign_fx_updates_without_new_closes(engine_db: None) -> None:
    day = date(2024, 1, 10)
    db.execute("INSERT INTO fx_rates VALUES (%s, 'DKK', 'USD', 7.10, 'ecb')", (day,))
    pnl_service.rebuild(1, through=day)
    result = DashboardResponse.model_validate(dashboard_service.dashboard())
    assert result.as_of == day
    assert result.fx_effect_base != 0


def test_dashboard_keeps_weekend_account_activity(engine_db: None) -> None:
    db.execute(
        "INSERT INTO ledger_transactions (connection_id, portfolio_id, broker_ref, kind, trade_date,"
        " currency, amount_local, account_currency, amount_account, base_currency, amount_base,"
        " description, source_endpoint, raw)"
        " VALUES (1, 1, 'weekend-fee', 'fee', '2024-01-06', 'DKK', -10, 'DKK', -10, 'DKK', -10,"
        " 'fee', 'test', '{}')"
    )
    pnl_service.rebuild(1, through=JAN[7])
    result = DashboardResponse.model_validate(dashboard_service.dashboard())
    assert result.as_of == JAN[6]
    assert result.daily_pnl == -10


def test_dashboard_base_currency_cash_needs_no_market_observations(engine_db: None) -> None:
    db.execute("DELETE FROM ledger_transactions WHERE kind <> 'deposit'")
    pnl_service.rebuild(1, through=JAN[9])
    result = DashboardResponse.model_validate(dashboard_service.dashboard())
    assert result.as_of == JAN[9]
    assert result.nav == 11000
    assert result.daily_pnl == 0


def test_dashboard_includes_today_as_intraday(engine_db: None) -> None:
    clock = db.select_one("SELECT CURRENT_DATE AS day")
    assert clock is not None
    today = clock["day"]
    for table, column in (
        ("ledger_transactions", "trade_date"),
        ("daily_prices", "price_date"),
        ("fx_rates", "rate_date"),
    ):
        db.execute(f"UPDATE {table} SET {column} = {column} + %s", ((today - JAN[9]).days,))
    pnl_service.rebuild(1, through=today)
    result = DashboardResponse.model_validate(dashboard_service.dashboard())
    assert result.as_of == today and result.intraday
    assert not any("pending" in warning for warning in result.warnings)
    assert result.nav == pnl_service.portfolio_days(1, date_lte=today)[-1]["nav"]
    assert all(row.day == today for row in result.top + result.bottom)

    # With no observation and no activity today only carries yesterday forward: fall back to the last observed day.
    db.execute("DELETE FROM ledger_transactions WHERE trade_date = %s", (today,))
    db.execute("DELETE FROM daily_prices WHERE price_date = %s", (today,))
    db.execute("DELETE FROM fx_rates WHERE rate_date = %s", (today,))
    pnl_service.rebuild(1, through=today)
    carried = DashboardResponse.model_validate(dashboard_service.dashboard())
    assert carried.as_of is not None and carried.as_of < today and not carried.intraday
    assert any("pending" in warning for warning in carried.warnings)


def test_dashboard_uses_common_date_and_flags_unbuilt_portfolios(engine_db: None) -> None:
    _rebuild()
    db.execute(
        "INSERT INTO broker_connections (broker, environment, access_token_encrypted, access_token_expires_at)"
        " VALUES ('saxo', 'live', 'x', CURRENT_TIMESTAMP), ('ibkr', 'sim', 'x', CURRENT_TIMESTAMP)"
    )
    db.execute("INSERT INTO portfolios (connection_id, name, base_currency) VALUES (2, 'Second', 'DKK')")
    # Another independent portfolio with the same fixture but shorter calculated coverage.
    db.execute(
        "INSERT INTO ledger_transactions (connection_id, portfolio_id, broker_ref, kind, trade_date,"
        " currency, amount_local, account_currency, amount_account, base_currency, amount_base,"
        " description, source_endpoint, raw)"
        " VALUES (2, 2, 'second-deposit', 'deposit', '2024-01-02', 'DKK', 5000, 'DKK', 5000, 'DKK', 5000,"
        " 'deposit', 'test', '{}')"
    )
    pnl_service.rebuild(2, through=JAN[8])
    db.execute("INSERT INTO portfolios (connection_id, name, base_currency) VALUES (3, 'Unbuilt', 'DKK')")
    result = DashboardResponse.model_validate(dashboard_service.dashboard())
    first = pnl_service.portfolio_days(1, date_lte=JAN[8])[-1]
    assert result.as_of == JAN[8]
    assert result.nav == first["nav"] + D(5000)
    assert close(result.daily_return_pct, first["daily_pnl"] / (first["nav_prev"] + D(5000)))
    assert result.series[-1].day == JAN[8]
    assert result.portfolios[0].nav == first["nav"]
    assert result.portfolios[2].nav is None
    assert len(result.warnings) == 2
    assert all(row.day == JAN[8] for row in result.top + result.bottom)

    db.execute("UPDATE portfolios SET reporting_start_date = '2024-01-09' WHERE id = 1")
    no_overlap = DashboardResponse.model_validate(dashboard_service.dashboard())
    assert no_overlap.nav is None and not no_overlap.series
    assert "no shared reporting date" in no_overlap.warnings[-1]

    db.execute("UPDATE portfolios SET base_currency = 'EUR' WHERE id = 2")
    mixed = DashboardResponse.model_validate(dashboard_service.dashboard())
    assert mixed.nav is None and mixed.as_of is None
    assert "different base currencies" in mixed.warnings[-1]


def test_identities_hold_exactly_for_every_row_and_day(engine_db: None) -> None:
    report = _rebuild()
    assert report["portfolio_rows"] == 8
    broken = db.select_one(
        "SELECT COUNT(*) FILTER (WHERE daily_pnl_base <> market_value_base - prev_market_value_base - flow_base)"
        "   AS position,"
        " COUNT(*) FILTER (WHERE daily_pnl_base <> price_effect_base + fx_effect_base + interaction_effect_base"
        "   + dividend_effect_base + interest_effect_base + cost_effect_base) AS decomposition"
        " FROM pnl_days"
    )
    assert broken == {"position": 0, "decomposition": 0}
    chain = db.select_one(
        "SELECT COUNT(*) FILTER (WHERE prev <> prev_market_value_base) AS broken FROM ("
        "  SELECT prev_market_value_base, LAG(market_value_base) OVER (PARTITION BY position_key ORDER BY day) AS prev"
        "  FROM pnl_days) x WHERE prev IS NOT NULL"
    )
    assert chain == {"broken": 0}
    portfolio = db.select_one(
        "SELECT COUNT(*) FILTER (WHERE daily_pnl <> nav - nav_prev - flow) AS broken,"
        " COUNT(*) FILTER (WHERE daily_pnl <> (SELECT COALESCE(SUM(daily_pnl_base), 0) FROM pnl_days x"
        "   WHERE x.day = d.day))"
        "   AS not_sum FROM portfolio_days d"
    )
    assert portfolio == {"broken": 0, "not_sum": 0}


def test_long_position_attribution_through_buy_move_dividend_and_sale(engine_db: None) -> None:
    _rebuild()
    aaa = _rows("sec:1")
    buy = aaa[JAN[3]]
    assert (buy["quantity"], buy["execution_price"], buy["execution_fx"]) == (D(10), D(100), D("6.90"))
    assert (buy["price"], buy["fx"]) == (D(102), D("6.95"))
    assert buy["market_value_base"] == D(7089) and buy["trade_flow_base"] == D(6900)
    assert buy["price_effect_base"] == D(138)  # 10 * (102 - 100) * 6.90
    assert buy["fx_effect_base"] == D(50)  # 1000 * (6.95 - 6.90)
    assert buy["interaction_effect_base"] == D(1)  # 10 * 2 * 0.05
    assert buy["cost_effect_base"] == D("-20.70") and buy["daily_pnl_base"] == D("168.30")
    assert buy["flow_base"] == D("6920.70")
    assert close(buy["daily_return_pct"], D("168.30") / D(6900))  # day one: over the traded amount
    assert buy["price_effect_local"] == D(20) and buy["daily_pnl_local"] == D(17)

    move = aaa[JAN[4]]
    assert (move["price_effect_base"], move["fx_effect_base"], move["interaction_effect_base"]) == (
        D("-69.5"),
        D(51),
        D("-0.5"),
    )
    assert move["daily_pnl_base"] == D(-19) and close(move["daily_return_pct"], D(-19) / D(7089))
    assert close(move["constant_currency_return_pct"], D(-10) * D("6.95") / D(7089))

    weekend = aaa[JAN[6]]
    assert weekend["daily_pnl_base"] == 0 and weekend["price_date"] == JAN[5] and weekend["fx_date"] == JAN[5]

    dividend = aaa[JAN[8]]
    assert (dividend["dividend_effect_base"], dividend["cost_effect_base"]) == (D(35), D("-5.25"))
    assert dividend["dividend_effect_local"] == D(5) and dividend["cost_effect_local"] == D("-0.75")
    assert dividend["daily_pnl_base"] == D("29.75") and dividend["flow_base"] == D("-29.75")
    assert dividend["market_value_base"] == dividend["prev_market_value_base"] == D(7070)

    sale = aaa[JAN[9]]
    assert sale["quantity"] == 0 and sale["market_value_base"] == 0 and sale["trade_flow_base"] == D(-7455)
    assert sale["price_effect_base"] == D(281) and sale["fx_effect_base"] == D(103)
    assert sale["interaction_effect_base"] == D(1) and sale["daily_pnl_base"] == D(385)
    assert sale["total_pnl_base"] == D("168.30") - 19 + D("29.75") + 385
    assert not db.select("SELECT 1 FROM pnl_days WHERE position_key = 'sec:1' AND day > %s", (JAN[9],))


def test_unitized_series_is_unaffected_by_flows(engine_db: None) -> None:
    _rebuild()
    days = {row["day"]: row for row in db.select("SELECT * FROM portfolio_days ORDER BY day")}
    first = days[JAN[2]]
    assert (first["nav"], first["flow"], first["daily_pnl"], first["unit_price"], first["units"]) == (
        D(10000),
        D(10000),
        D(0),
        D(100),
        D(100),
    )
    # 3rd: AAA 7089 + BBB 5560 + CCC 4170 + DDD -1000.8 + cash 10000 - 6900 - 20.70 - 5520 - 4140 + 1035
    third = days[JAN[3]]
    assert third["nav"] == D("10272.50") and third["daily_pnl"] == D("272.50")
    assert close(third["daily_return_pct"], D("272.50") / D(10000))
    assert third["unit_price"] == D("102.725")
    assert third["units"] == D(100)
    eighth = days[JAN[8]]
    assert eighth["flow"] == D(1000)
    # the deposit buys units at the day's price, so the unit price only moves with PnL
    assert close(eighth["unit_price"], days[JAN[5]]["unit_price"] * (1 + eighth["daily_pnl"] / days[JAN[5]]["nav"]))
    assert close(eighth["units"], eighth["nav"] / eighth["unit_price"])
    assert eighth["units"] > days[JAN[5]]["units"]
    assert all(row["drawdown_pct"] <= 0 for row in days.values())
    assert close(days[JAN[9]]["cumulative_return_pct"], days[JAN[9]]["unit_price"] / 100 - 1)


def test_booked_split_keeps_the_position_continuous(engine_db: None) -> None:
    _rebuild()
    bbb = _rows("sec:2")
    assert bbb[JAN[3]]["quantity"] == D(8) and bbb[JAN[3]]["basis_factor"] == D(2)
    assert bbb[JAN[3]]["execution_price"] == D(100) and bbb[JAN[3]]["price_effect_base"] == 0
    split_day = bbb[JAN[4]]
    assert split_day["quantity_prev"] == D(8) and split_day["quantity"] == D(8) and split_day["trade_quantity"] == 0
    assert split_day["trade_flow_base"] == 0 and split_day["basis_factor"] == D(1)
    assert split_day["daily_pnl_base"] == D(96)  # 8*(101-100)*6.95 + 8*100*0.05 + 8*1*0.05
    assert split_day["market_value_base"] == D(5656)


def test_unbooked_split_is_inferred_from_the_trade_price(engine_db: None) -> None:
    _rebuild()
    ccc = _rows("sec:3")
    assert ccc[JAN[3]]["quantity"] == D(4) and ccc[JAN[3]]["inferred_split"] == D(2)
    assert ccc[JAN[3]]["execution_price"] == D(150) and ccc[JAN[3]]["price"] == D(150)
    assert ccc[JAN[3]]["market_value_base"] == D(4) * 150 * D("6.95")
    issue = db.select_one("SELECT amount, day FROM reconciliation_issues WHERE kind = 'inferred_split'")
    assert issue == {"amount": D(2), "day": JAN[3]}
    snapped = db.select(
        "SELECT snap_split_ratio(19.94) AS a, snap_split_ratio(0.0993) AS b, snap_split_ratio(1.15) AS c,"
        " snap_split_ratio(1.62) AS d"
    )[0]
    assert (snapped["a"], snapped["b"], snapped["c"], snapped["d"]) == (20, D("0.1"), 1, D("1.62"))


def test_short_position_signs_and_returns(engine_db: None) -> None:
    _rebuild()
    ddd = _rows("sec:4")
    row = ddd[JAN[3]]
    assert row["quantity"] == D(-3) and row["market_value_base"] == D("-1000.8") and row["trade_flow_base"] == D(-1035)
    assert row["daily_pnl_base"] == D("34.2") and close(row["daily_return_pct"], D("34.2") / D(1035))
    rows, total = pnl_service.list_pnl_rows(
        pnl_service.PnlFilter(position_type="short", position_kind="security"), Page(1, 100, "day", "asc")
    )
    assert total == len(rows) and {r["position_key"] for r in rows} == {"sec:4"}
    assert rows[0]["position_type"] == "short"


def test_cash_conversion_nets_to_zero_and_foreign_cash_earns_fx_effect(engine_db: None) -> None:
    _rebuild()
    usd = _rows("cash:USD")
    dkk = _rows("cash:DKK")
    assert usd[JAN[8]]["quantity"] == D(100) and usd[JAN[8]]["trade_flow_base"] == D(700)
    assert usd[JAN[8]]["market_value_base"] == D(700) and usd[JAN[8]]["daily_pnl_base"] == 0
    assert dkk[JAN[8]]["trade_flow_base"] == D(1000) - 700 + 35 - D("5.25")
    assert dkk[JAN[8]]["cost_effect_base"] == 0  # nothing left over from the paired transfer
    assert usd[JAN[9]]["fx_effect_base"] == D(5) and usd[JAN[9]]["daily_pnl_base"] == D(5)
    assert usd[JAN[9]]["market_value_base"] == D(705) + D("7455") - D("7455")  # sale settled in DKK, not USD
    assert all(row["daily_pnl_base"] == 0 for row in dkk.values())
    assert (
        dkk[JAN[9]]["quantity"]
        == D(10000) - 6900 - D("20.70") - 5520 - 4140 + 1035 + 35 - D("5.25") + 1000 - 700 + 7455
    )


def test_nav_difference_splits_into_fx_cash_and_securities(engine_db: None) -> None:
    _rebuild()
    # The broker values USD at 7.00 on the 9th where ECB says 7.05; the 8th has no broker USD rate.
    for day, currency, rate in ((JAN[8], "DKK", "1"), (JAN[9], "DKK", "1"), (JAN[9], "USD", "7.00")):
        db.execute(
            "INSERT INTO broker_fx_rates (portfolio_id, rate_date, currency, rate, quote_currency, quote_rate)"
            " VALUES (1, %s, %s, %s, 'DKK', %s)",
            (day, currency, D(rate), D(rate)),
        )
    held = db.select(
        "SELECT position_kind, currency, market_value_local, market_value_base FROM pnl_days"
        " WHERE day = %s AND market_value_local <> 0",
        (JAN[9],),
    )
    broker_rate = {"DKK": D(1), "USD": D("7.00")}
    cash = sum(
        row["market_value_local"] * broker_rate[row["currency"]] for row in held if row["position_kind"] == "cash"
    )
    securities = sum(
        row["market_value_local"] * broker_rate[row["currency"]] for row in held if row["position_kind"] == "security"
    )
    assert any(row["currency"] == "USD" for row in held)
    # The broker reports 1000 less cash and 25 more in securities than the engine holds at its rates.
    for day in (JAN[8], JAN[9]):
        db.execute(
            "INSERT INTO cash_snapshots (connection_id, portfolio_id, snapshot_date, account_key, currency,"
            " cash_balance, total_value, raw, fetched_at)"
            " VALUES (1, 1, %s, '', 'DKK', %s, %s, '{}', CURRENT_TIMESTAMP)",
            (day, cash - 1000, cash - 1000 + securities + 25),
        )
    _rebuild()
    days = {row["day"]: row for row in db.select("SELECT * FROM portfolio_days")}
    ninth = days[JAN[9]]
    assert ninth["gap_cash"] == D(1000) and ninth["gap_securities"] == D(-25)
    assert ninth["gap_fx"] == sum(row["market_value_base"] for row in held) - cash - securities
    assert ninth["gap_fx"] > 0  # USD holdings at ECB's 7.05 against the broker's 7.00
    assert ninth["nav"] - ninth["broker_value"] == ninth["gap_fx"] + ninth["gap_cash"] + ninth["gap_securities"]
    assert (days[JAN[8]]["gap_fx"], days[JAN[8]]["gap_cash"], days[JAN[8]]["gap_securities"]) == (None, None, None)

    # The issue read model shows both rates per held currency; the effects add up to gap_fx.
    [issue] = [row for row in pnl_service.list_issues() if row["kind"] == "nav_mismatch" and row["day"] == JAN[9]]
    rates = {rate["currency"]: rate for rate in issue["fx_rates"]}
    assert rates["USD"]["ecb_rate"] == D("7.05") and rates["USD"]["broker_rate"] == D("7.00")
    assert rates["DKK"]["ecb_rate"] == rates["DKK"]["broker_rate"] == D(1) and rates["DKK"]["gap_fx"] == 0
    assert sum(rate["gap_fx"] for rate in issue["fx_rates"]) == issue["gap_fx"]
    assert issue["fx_rates"][0]["currency"] == "USD"  # largest effect first


def test_read_models(engine_db: None) -> None:
    _rebuild()
    rows, total = pnl_service.list_pnl_rows(
        pnl_service.PnlFilter(date_gte=JAN[3], date_lte=JAN[3], position_kind="security"),
        Page(1, 10, "market_value_base", "desc"),
    )
    assert total == 4 and [r["full_ticker"] for r in rows] == ["AAA:XNAS", "BBB:XNAS", "CCC:XNAS", "DDD:XNAS"]
    assert rows[0]["security_name"] == "AAA Inc" and rows[0]["position_type"] == "long"
    rows, total = pnl_service.list_pnl_rows(pnl_service.PnlFilter(search="cash usd"), Page(1, 10, "day", "asc"))
    assert total == 0  # search matches names, tickers and currencies, not the synthetic cash label
    rows, total = pnl_service.list_pnl_rows(
        pnl_service.PnlFilter(position_kind="cash", search="usd"), Page(1, 10, "day", "asc")
    )
    assert total == 2 and rows[0]["security_name"] == "Cash USD" and rows[0]["full_ticker"] == "USD"

    single = pnl_service.portfolio_days(1)
    total_series = pnl_service.portfolio_days(None)
    assert all(close(a["unit_price"], b["unit_price"]) for a, b in zip(single, total_series, strict=True))
    assert total_series[0]["portfolio_name"] == "Total" and total_series[0]["portfolio_id"] == 0
    summary = pnl_service.series_summary(single)
    assert summary["days"] == 8 and summary["annualized_return_pct"] is None
    assert close(summary["period_return_pct"], single[-1]["unit_price"] / 100 - 1)
    sliced = pnl_service.portfolio_days(1, date_gte=JAN[4])
    assert close(
        pnl_service.series_summary(sliced)["period_return_pct"], single[-1]["unit_price"] / single[1]["unit_price"] - 1
    )
    counted = db.select("SELECT COUNT(*) AS n FROM pnl_days")[0]["n"]
    assert pnl_service.engine_status()[0]["position_rows"] == counted
