"""Reporting boundaries are projections; changing them must not change accounting history."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest
from litestar.testing import TestClient
from test_pnl_engine_integration import JAN, close
from test_pnl_engine_integration import engine_db as engine_db

from app import db
from app.api import app
from app.routes.ledger import PositionDetail, PositionRow
from app.services import dashboard_service, ledger_queries, pnl_service, position_service
from app.services.ledger_queries import Page


def set_start(value: date | None) -> None:
    db.execute("UPDATE portfolios SET reporting_start_date = %s WHERE id = 1", (value,))


def prepare_positions() -> None:
    pnl_service.rebuild(1, through=JAN[9])
    position_service.rebuild(1)
    db.execute(
        "INSERT INTO position_snapshots (connection_id, portfolio_id, snapshot_date, broker_position_id, security_id,"
        " quantity, current_price, currency, market_value_local, market_value_base, fx_rate_base, raw, fetched_at)"
        " SELECT 1, 1, d.day, d.security_id::text, d.security_id, pos.quantity, d.price * pos.basis_factor,"
        " d.currency, d.market_value_local, d.market_value_base, d.fx, '{}', CURRENT_TIMESTAMP"
        " FROM pnl_days d JOIN positions pos ON pos.portfolio_id = d.portfolio_id AND pos.security_id = d.security_id"
        " WHERE d.day = '2024-01-09' AND d.position_kind = 'security' AND pos.closed IS NULL"
    )


@pytest.mark.parametrize("start", [JAN[4], JAN[6], JAN[8], JAN[9]])
def test_reporting_rebases_returns_pnl_and_drawdown_without_rewriting_history(engine_db: None, start: date) -> None:
    pnl_service.rebuild(1, through=JAN[9])
    original = pnl_service.portfolio_days(1)
    ledger_before = db.select("SELECT * FROM ledger_transactions ORDER BY id")
    raw_before = db.select("SELECT * FROM portfolio_days ORDER BY day")
    set_start(start)
    rows = pnl_service.portfolio_days(1, date_gte=JAN[2])
    assert rows[0]["day"] == start
    previous = next(row for row in original if row["day"].toordinal() == start.toordinal() - 1)
    for row in rows:
        old = next(item for item in original if item["day"] == row["day"])
        assert row["nav"] == old["nav"] and row["flow"] == old["flow"]
        assert close(row["unit_price"], old["unit_price"] / previous["unit_price"] * 100, places=7)
        assert close(row["cumulative_return_pct"], row["unit_price"] / 100 - 1)
        assert close(row["units"] * row["unit_price"], row["nav"], places=6)
    assert close(rows[0]["drawdown_pct"], min(D(0), rows[0]["daily_return_pct"]))
    assert close(pnl_service.series_summary(rows)["period_return_pct"], rows[-1]["cumulative_return_pct"])
    assert close(pnl_service.series_summary(rows)["max_drawdown_pct"], min(row["drawdown_pct"] for row in rows))
    reported, _ = pnl_service.list_pnl_rows(pnl_service.PnlFilter(), Page(1, 1000, "day", "asc"))
    for key in {row["position_key"] for row in reported}:
        position_rows = [row for row in reported if row["position_key"] == key]
        assert position_rows[-1]["total_pnl_base"] == sum(row["daily_pnl_base"] for row in position_rows)
    dashboard = dashboard_service.dashboard()
    assert dashboard["series"][0]["day"] == start
    assert close(dashboard["portfolios"][0]["cumulative_return_pct"], rows[-1]["cumulative_return_pct"])
    transactions, count = ledger_queries.list_transactions(
        ledger_queries.TransactionFilter(), Page(1, 1000, "trade_date", "asc")
    )
    assert count == len(transactions) and all(row["trade_date"] >= start for row in transactions)
    assert all(row["trade_date"] >= start for row in ledger_queries.list_cash_movements())
    assert db.select("SELECT * FROM ledger_transactions ORDER BY id") == ledger_before
    assert db.select("SELECT * FROM portfolio_days ORDER BY day") == raw_before
    set_start(None)
    assert pnl_service.portfolio_days(1) == original


def test_carry_in_positions_keep_ids_holdings_and_acquisition_costs(engine_db: None) -> None:
    prepare_positions()
    original = position_service.list_positions(as_of=JAN[9])
    set_start(JAN[4])
    rows = position_service.list_positions(as_of=JAN[9])
    assert {r["id"] for r in rows} == {r["id"] for r in original}
    for row in rows:
        PositionRow.model_validate(row)
        detail = position_service.position_detail(row["id"], as_of=JAN[9])
        assert detail is not None
        PositionDetail.model_validate(detail)
        assert detail["reporting_start_date"] == JAN[4]
        assert all(t["trade_date"] >= JAN[4] for t in detail["trades"])
        assert all(t["date"] >= JAN[4] for t in detail["series"])
        daily = db.select("SELECT * FROM pnl_days WHERE security_id = %s AND day >= %s", (row["security_id"], JAN[4]))
        assert close(row["return_base"], sum(day["daily_pnl_base"] for day in daily), places=6)
        assert row["quantity"] == next(r["quantity"] for r in original if r["id"] == row["id"])
        if row["security_id"] == 1:
            assert detail["returns_base"]["opening_value"] == D(7089)
            assert detail["original_cost_base"] == D(-6900)
            assert detail["returns_base"]["total_cost"] == 0
            assert detail["returns_base"]["return_amount"] == D("395.75")
        if row["security_id"] == 2:
            assert detail["series"][0]["quantity"] == 8  # bought before the date, split on the date
        if row["security_id"] == 4:
            assert detail["returns_base"]["opening_value"] < 0  # short carry-in
            assert row["invested_base"] == abs(detail["returns_base"]["opening_value"])
    set_start(date(2024, 1, 10))
    assert 1 not in {r["security_id"] for r in position_service.list_positions(as_of=JAN[9])}
    aaa = next(r for r in original if r["security_id"] == 1)
    assert position_service.position_detail(aaa["id"]) is None
    assert all(r["return_base"] is None for r in position_service.list_positions(as_of=JAN[9]))
    set_start(None)
    assert position_service.list_positions(as_of=JAN[9]) == original


def test_combined_entry_capital_is_a_flow_not_a_gain(engine_db: None) -> None:
    pnl_service.rebuild(1, through=JAN[9])
    db.execute(
        "INSERT INTO portfolios (name, base_currency, reporting_start_date) VALUES ('Second', 'DKK', '2024-01-08')"
    )
    db.execute(
        "INSERT INTO portfolio_days (portfolio_id, day, base_currency, nav, positions_value, cash_value, nav_prev,"
        " flow, daily_pnl, daily_return_pct, unit_price, units, cumulative_return_pct, drawdown_pct)"
        " VALUES (2, '2024-01-08', 'DKK', 1001000, 1001000, 0, 1000000, 0, 1000, 0.001, 100.1, 10000, 0.001, 0),"
        " (2, '2024-01-09', 'DKK', 1001000, 1001000, 0, 1001000, 0, 0, 0, 100.1, 10000, 0.001, 0)"
    )
    combined = pnl_service.portfolio_days(None)
    first = pnl_service.portfolio_days(1)
    for row in combined[1:]:
        assert row["nav"] - row["nav_prev"] - row["flow"] == row["daily_pnl"]
    entry = next(row for row in combined if row["day"] == JAN[8])
    underlying = next(row for row in first if row["day"] == JAN[8])
    assert entry["flow"] == underlying["flow"] + D(1000000)
    assert close(entry["daily_return_pct"], (underlying["daily_pnl"] + 1000) / (underlying["nav_prev"] + 1000000))
    assert entry["daily_return_pct"] < D("0.01")
    sliced = pnl_service.portfolio_days(None, date_gte=JAN[9])
    assert sliced[0]["drawdown_pct"] == combined[-1]["drawdown_pct"]
    db.execute("DELETE FROM portfolio_days WHERE portfolio_id = 2 AND day = '2024-01-09'")
    assert pnl_service.portfolio_days(None)[-1]["day"] == JAN[8]
    set_start(JAN[9])
    assert pnl_service.portfolio_days(None) == []


def test_patch_date_and_name_are_independent_and_validate_dates(engine_db: None) -> None:
    prepare_positions()
    with TestClient(app=app) as client:
        client.headers["host"] = "localhost"  # an allowed host; the default test host is not
        renamed = client.patch("/api/portfolios/1", json={"display_name": "Pension"})
        assert renamed.status_code == 200
        response = client.patch("/api/portfolios/1", json={"reporting_start_date": "2024-01-04"})
        assert response.status_code == 200
        assert response.json()["display_name"] == "Pension"
        assert response.json()["reporting_start_date"] == "2024-01-04"
        assert (
            client.patch("/api/portfolios/1", json={"display_name": "Savings"}).json()["reporting_start_date"]
            == "2024-01-04"
        )
        for invalid in ("invalid", "2024-02-30", "2999-01-01"):
            assert client.patch("/api/portfolios/1", json={"reporting_start_date": invalid}).status_code == 400
        assert client.patch("/api/portfolios/999", json={"reporting_start_date": None}).status_code == 404
        cleared = client.patch("/api/portfolios/1", json={"reporting_start_date": None}).json()
        assert cleared["reporting_start_date"] is None and cleared["display_name"] == "Savings"


def test_dormant_loss_then_large_deposit_and_doubling(engine_db: None) -> None:
    db.execute(
        "INSERT INTO portfolio_days (portfolio_id, day, base_currency, nav, positions_value, cash_value, nav_prev,"
        " flow, daily_pnl, daily_return_pct, unit_price, units, cumulative_return_pct, drawdown_pct) VALUES"
        " (1, '2024-01-02', 'DKK', 10000, 10000, 0, 0, 10000, 0, NULL, 100, 100, 0, 0),"
        " (1, '2024-01-03', 'DKK', 1000, 1000, 0, 10000, 0, -9000, -0.9, 10, 100, -0.9, -0.9),"
        " (1, '2024-01-04', 'DKK', 1001000, 1001000, 0, 1000, 1000000, 0, 0, 10, 100100, -0.9, -0.9),"
        " (1, '2024-01-05', 'DKK', 2002000, 2002000, 0, 1001000, 0, 1001000, 1, 20, 100100, -0.8, -0.8)"
    )
    original = pnl_service.portfolio_days(1)
    assert original[-1]["cumulative_return_pct"] == D("-0.8")
    set_start(JAN[4])
    first, second = pnl_service.portfolio_days(1)
    assert first["unit_price"] == 100 and first["cumulative_return_pct"] == 0
    assert first["nav_prev"] == 1000 and first["flow"] == 1000000
    assert second["unit_price"] == 200 and second["cumulative_return_pct"] == 1
    assert second["drawdown_pct"] == 0
    assert pnl_service.series_summary([first, second])["period_return_pct"] == 1
    # First-day losses count even without an earlier displayed row.
    set_start(JAN[3])
    loss_day = pnl_service.portfolio_days(1)[0]
    assert loss_day["drawdown_pct"] == D("-0.9")
    assert pnl_service.series_summary([loss_day])["max_drawdown_pct"] == D("-0.9")
    # Before inception means all available data; after coverage means an empty report.
    set_start(date(2024, 1, 1))
    assert pnl_service.portfolio_days(1)[-1]["unit_price"] == 20
    set_start(JAN[9])
    assert pnl_service.portfolio_days(1) == []
    assert pnl_service.portfolio_days(None) == []
    set_start(None)
    assert pnl_service.portfolio_days(1) == original
