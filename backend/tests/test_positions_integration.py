"""rebuild_positions() against real PostgreSQL; needs TEST_DATABASE_URL.

Scenarios: a booked split, a security re-opened after a close with late income, costs linked to
their trade against unlinked ones, a cost in another currency, stable ids across rebuilds, and a
position that disappears when its ledger rows do.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app import db
from app.services import position_service

D = Decimal


@pytest.fixture
def positions_db(migrated_db: None) -> Iterator[None]:
    db.execute(
        "INSERT INTO broker_connections"
        " (broker, environment, access_token_encrypted, access_token_expires_at)"
        " VALUES ('saxo', 'sim', 'x', CURRENT_TIMESTAMP)"
    )
    db.execute("INSERT INTO portfolios (connection_id, name, base_currency) VALUES (1, 'Test', 'DKK')")
    db.execute(
        "INSERT INTO securities (broker, uic, asset_type, symbol, ticker, mic, name, currency, raw)"
        " VALUES ('saxo', 1, 'Stock', 'TTD:xnas', 'TTD', 'XNAS', 'The Trade Desk', 'USD', '{}'),"
        "        ('saxo', 2, 'Stock', 'AAA:xnas', 'AAA', 'XNAS', 'AAA Inc', 'USD', '{}')"
    )
    yield


def ledger(
    ref: str,
    kind: str,
    day: str,
    quantity: str | None = None,
    price: str | None = None,
    *,
    local: str = "0",
    base: str = "0",
    security_id: int = 1,
    currency: str = "USD",
    fx: str | None = None,
    related: str | None = None,
    account: tuple[str, str] | None = None,
    executed_at: str | None = None,
) -> None:
    raw = f'{{"TradeExecutionTime": "{executed_at}"}}' if executed_at else "{}"
    db.execute(
        "INSERT INTO ledger_transactions (connection_id, portfolio_id, broker_ref, kind, trade_date, security_id,"
        " quantity, price, currency, amount_local, account_currency, amount_account, base_currency, amount_base,"
        " fx_rate_base, related_ref, source_endpoint, raw)"
        " VALUES (1, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'DKK', %s, %s, %s, 'test', %s)",
        (
            ref,
            kind,
            date.fromisoformat(day),
            security_id,
            quantity,
            price,
            currency,
            D(local),
            account[0] if account else None,
            D(account[1]) if account else None,
            D(base),
            fx,
            related,
            raw,
        ),
    )


def close(security_id: int, day: str, price: str) -> None:
    db.execute(
        "INSERT INTO daily_prices (security_id, price_date, close, currency, source)"
        " VALUES (%s, %s, %s, 'USD', 'saxo')",
        (security_id, date.fromisoformat(day), D(price)),
    )


def positions() -> list[dict[str, Any]]:
    return db.select("SELECT * FROM positions ORDER BY security_id, opened")


def test_split_keeps_the_position_and_adjusts_shares_and_average_price(positions_db: None) -> None:
    ledger("t1", "trade", "2021-05-03", "1", "806", local="-806", base="-5000", fx="6.2")
    ledger("b1", "commission", "2021-05-03", local="-3", base="-18", related="t1")
    ledger("c1", "corporate_action", "2021-06-17", "-1", "806")
    ledger("c2", "corporate_action", "2021-06-17", "10", "80.6")
    ledger("d1", "dividend", "2021-07-01", local="2", base="12")
    ledger("t2", "trade", "2021-08-02", "-10", "90", local="900", base="5600", fx="6.22")
    assert position_service.rebuild(1) == {"portfolio_id": 1, "position_rows": 1, "link_rows": 6}

    [row] = positions()
    assert row["opened"] == date(2021, 5, 3) and row["closed"] == date(2021, 8, 2) and row["quantity"] == 0
    assert row["buys"] == 1 and row["sells"] == 1
    assert row["shares_bought"] == D("10") and row["shares_sold"] == D("10")  # 1 share scaled by the split
    assert row["avg_buy_price"] == D("80.6") and row["avg_sell_price"] == D("90") and row["basis_factor"] == 1
    factors = db.select("SELECT basis_factor FROM position_transactions ORDER BY transaction_id")
    assert [f["basis_factor"] for f in factors] == [D("10"), None, D("1"), D("1"), None, D("1")]
    assert row["buy_cash_base"] == D("5000") and row["invested_base"] == D("5018")
    assert row["sell_cash_base"] == D("5600") and row["dividends_base"] == D("12") and row["costs_base"] == D("-18")
    assert row["invested_local"] == D("809") and row["dividends_local"] == D("2")
    links = db.select("SELECT role, funding FROM position_transactions ORDER BY transaction_id")
    assert [(link["role"], link["funding"]) for link in links] == [
        ("trade", False),
        ("cost", True),
        ("corporate_action", False),
        ("corporate_action", False),
        ("income", False),
        ("trade", False),
    ]


def test_reopened_security_gets_a_second_position_and_late_income_stays_with_the_closed_one(
    positions_db: None,
) -> None:
    ledger("t1", "trade", "2021-01-04", "5", "100", local="-500", base="-3000")
    ledger("t2", "trade", "2021-02-01", "-5", "110", local="550", base="3300")
    ledger("d1", "dividend", "2021-02-10", local="1", base="9")
    ledger("t3", "trade", "2022-01-04", "-2", "120", local="240", base="1500")
    position_service.rebuild(1)
    first, second = positions()
    assert first["closed"] == date(2021, 2, 1) and first["dividends_base"] == D("9")
    assert second["opened"] == date(2022, 1, 4) and second["closed"] is None
    assert second["position_type"] == "short" and second["quantity"] == D("-2")


def test_costs_follow_their_trade_and_only_buy_side_costs_fund_the_position(positions_db: None) -> None:
    ledger("t1", "trade", "2021-01-04", "10", "100", local="-1000", base="-7000")
    ledger("b1", "commission", "2021-01-04", local="-3", base="-20", related="t1")
    ledger("t2", "trade", "2021-03-01", "-10", "120", local="1200", base="8400")
    ledger("b2", "commission", "2021-03-01", local="-4", base="-25", related="t2")
    ledger("b3", "fee", "2021-03-15", local="-1", base="-5")  # unlinked: the last position opened before
    ledger("t3", "trade", "2022-01-04", "4", "130", local="-520", base="-3600")
    ledger("b4", "commission", "2022-01-05", local="-1", base="-2", related="t2")  # late, but linked to the sale
    position_service.rebuild(1)
    first, second = positions()
    assert first["invested_base"] == D("7020") and first["costs_base"] == D("-52")
    assert second["invested_base"] == D("3600") and second["costs_base"] == D("0")


def test_foreign_currency_cost_rows_convert_at_the_trade_fx(positions_db: None) -> None:
    ledger("t1", "trade", "2024-01-02", "10", "100", local="-1000", base="-7000", fx="7")
    ledger("b1", "commission", "2024-01-02", local="-14", base="-14", currency="DKK", related="t1")
    ledger("b2", "fee", "2024-02-01", local="-21", base="-21", currency="DKK")  # unlinked: latest trade FX, 7
    ledger("t2", "trade", "2024-06-03", "-10", "120", local="1200", base="9600", fx="8")
    position_service.rebuild(1)
    [row] = positions()
    assert row["invested_local"] == D("1002") and row["invested_base"] == D("7014")
    assert row["costs_local"] == D("-5") and row["costs_base"] == D("-35")


def test_ids_survive_rebuilds_and_unsupported_positions_are_deleted(positions_db: None) -> None:
    ledger("t1", "trade", "2021-01-04", "5", "100", local="-500", base="-3000")
    ledger("t2", "trade", "2021-02-01", "-5", "110", local="550", base="3300")
    ledger("t3", "trade", "2021-03-01", "3", "50", local="-150", base="-1000", security_id=2)
    position_service.rebuild(1)
    before = {(row["security_id"], row["opened"]): row["id"] for row in positions()}
    assert len(before) == 2

    ledger("t4", "trade", "2021-04-01", "-3", "60", local="180", base="1200", security_id=2)
    assert position_service.rebuild(1, security_id=2)["position_rows"] == 1
    after = {(row["security_id"], row["opened"]): row["id"] for row in positions()}
    assert after == before  # same ids, the AAA position just closed
    assert [row["closed"] for row in positions()] == [date(2021, 2, 1), date(2021, 4, 1)]

    db.execute("DELETE FROM ledger_transactions WHERE security_id = 2")
    position_service.rebuild(1)
    assert [row["security_id"] for row in positions()] == [1]
    assert db.select_one("SELECT COUNT(*) AS n FROM position_transactions")["n"] == 2  # type: ignore[index]


def test_read_models_value_open_positions_at_the_mark(positions_db: None) -> None:
    ledger("t1", "trade", "2024-01-02", "10", "100", local="-1000", base="-7000", fx="7")
    ledger("d1", "dividend", "2024-03-01", local="10", base="70")
    position_service.rebuild(1)
    db.execute(
        "INSERT INTO position_snapshots (connection_id, portfolio_id, snapshot_date, broker_position_id, security_id,"
        " quantity, current_price, currency, market_value_local, market_value_base, fx_rate_base, raw, fetched_at)"
        " VALUES (1, 1, '2024-06-03', 'p1', 1, 10, 120, 'USD', 1200, 9600, 8, '{}', CURRENT_TIMESTAMP)"
    )
    [row] = position_service.list_positions(as_of=date(2024, 6, 3))
    assert row["status"] == "open" and row["value_base"] == D("9600") and row["return_base"] == D("2670")
    assert row["roi_pct"] == D("2670") / D("7000") and row["notes"] == []

    detail = position_service.position_detail(row["id"], as_of=date(2024, 6, 3))
    assert detail is not None
    assert detail["returns_local"]["value"] == D("1200") and detail["returns_local"]["return_amount"] == D("210")
    assert detail["returns_base"]["return_amount"] == D("2670")
    assert [trade["kind"] for trade in detail["trades"]] == ["buy"]
    assert position_service.position_detail(999) is None


def test_unbooked_split_is_inferred_from_the_trade_price_against_the_close(positions_db: None) -> None:
    # A stock bought and sold in 2021, 20:1 split in 2022; the price history is on the post-split basis
    close(1, "2021-01-07", "88.717")
    close(1, "2021-07-20", "126.2")
    close(1, "2021-07-21", "130")  # after the close: the detail series must stop at the closing date
    ledger("t1", "trade", "2021-01-07", "1", "1769.1", local="-1769.1", base="-10779.46", fx="6.093")
    ledger("t2", "trade", "2021-07-20", "-1", "2515.6", local="2515.6", base="15836.33", fx="6.295")
    position_service.rebuild(1)
    [row] = positions()
    assert row["basis_factor"] == D("20") and row["shares_bought"] == D("20") and row["shares_sold"] == D("20")
    assert row["avg_buy_price"] == D("88.455") and row["avg_sell_price"] == D("125.78")
    assert row["buy_cash_base"] == D("10779.46")  # cash is cash, whatever the basis
    factors = db.select("SELECT basis_factor FROM position_transactions ORDER BY transaction_id")
    assert [f["basis_factor"] for f in factors] == [D("20"), D("20")]
    detail = position_service.position_detail(row["id"], as_of=date(2021, 8, 1))
    assert detail is not None
    assert [trade["adjusted_price"] for trade in detail["trades"]] == [D("88.455"), D("125.78")]
    assert [(point["quantity"], point["market_value"]) for point in detail["series"]] == [
        (D("20"), D("1774.340")),
        (D("0"), D("0")),
    ]
    history = [point["date"] for point in detail["price_history"]]
    assert history == [date(2021, 1, 7), date(2021, 7, 20), date(2021, 7, 21)]  # price context runs past the close


def test_corporate_action_legs_that_net_to_zero_open_no_position(positions_db: None) -> None:
    ledger("c1", "corporate_action", "2021-08-12", "70", "13.7")
    ledger("c2", "corporate_action", "2021-08-12", "-70", "13.7")
    ledger("t1", "trade", "2021-09-01", "5", "10", local="-50", base="-320", fx="6.4")
    assert position_service.rebuild(1) == {"portfolio_id": 1, "position_rows": 1, "link_rows": 1}
    [row] = positions()
    assert row["opened"] == date(2021, 9, 1) and row["buys"] == 1


def test_base_amounts_use_the_account_amount_on_base_currency_accounts(positions_db: None) -> None:
    # Saxo's client-currency figure carries rounding noise even for a DKK account; the account amount is exact
    ledger("t1", "trade", "2024-01-02", "10", "100", local="-1000", base="-7000.03", fx="7", account=("DKK", "-7000"))
    ledger("d1", "dividend", "2024-03-01", local="10", base="70.02", account=("DKK", "70"))
    ledger("f1", "fee", "2024-03-01", local="-1", base="-7.01", account=("USD", "-1"))
    position_service.rebuild(1)
    [row] = positions()
    assert row["buy_cash_base"] == D("7000") and row["dividends_base"] == D("70") and row["costs_base"] == D("-7.01")


def test_same_day_trades_follow_the_execution_time_not_the_ledger_order(positions_db: None) -> None:
    ledger("t1", "trade", "2026-08-21", "1", "4874", local="-4874", base="-31203", fx="6.4")
    # inserted first but executed later: the sell at 11:37 closes the position before this buy reopens it
    ledger(
        "t2",
        "trade",
        "2026-09-10",
        "1",
        "4800",
        local="-4800",
        base="-30906",
        fx="6.44",
        executed_at="2026-09-10T13:56:54Z",
    )
    ledger(
        "t3",
        "trade",
        "2026-09-10",
        "-1",
        "4970",
        local="4970",
        base="32001",
        fx="6.44",
        executed_at="2026-09-10T11:37:02Z",
    )
    position_service.rebuild(1)
    rows = positions()
    assert [(row["opened"], row["closed"], row["quantity"]) for row in rows] == [
        (date(2026, 8, 21), date(2026, 9, 10), D("0")),
        (date(2026, 9, 10), None, D("1")),
    ]
