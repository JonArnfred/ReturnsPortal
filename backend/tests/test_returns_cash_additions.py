"""Lifetime contributions must survive both report boundaries and API date filters."""

from datetime import date
from decimal import Decimal as D

import pytest
from litestar.testing import TestClient
from test_pnl_engine_integration import JAN, close
from test_pnl_engine_integration import engine_db as engine_db

from app import db
from app.api import app
from app.services import pnl_service


@pytest.mark.parametrize("portfolio_id", [1, 0])
def test_lifetime_additions_include_withdrawals_and_ignore_reporting_window(engine_db: None, portfolio_id: int) -> None:
    # A withdrawal reduces invested capital, not investment returns.
    db.execute(
        "INSERT INTO ledger_transactions (portfolio_id, connection_id, broker_ref, kind, trade_date, currency,"
        " amount_local, account_currency, amount_account, amount_base, base_currency, source_endpoint, raw)"
        " VALUES (1, 1, 'withdrawal-test', 'withdrawal', '2024-01-09', 'DKK', -500, 'DKK', -500, -500,"
        " 'DKK', 'test', '{}')"
    )
    pnl_service.rebuild(1, through=JAN[9])
    history = pnl_service.portfolio_days(portfolio_id)
    expected = {day: D(10000 if day < JAN[8] else 11000 if day == JAN[8] else 10500) for day in JAN.values()}
    for row in history:
        assert row["cumulative_cash_additions"] == expected[row["day"]]
        assert row["returns_base"] == row["nav"] - expected[row["day"]]
        assert close(row["returns_base"], sum(r["daily_pnl"] for r in history if r["day"] <= row["day"]))

    db.execute("UPDATE portfolios SET reporting_start_date = '2024-01-04' WHERE id = 1")
    with TestClient(app=app) as client:
        client.headers["host"] = "localhost"  # an allowed host; the default test host is not
        response = client.get(
            "/api/reports/portfolio-days",
            params={"portfolio_id": portfolio_id, "date_gte": "2024-01-05", "date_lte": "2024-01-08"},
        )
    assert response.status_code == 200
    rows = response.json()["data"]
    assert rows[0]["day"] == "2024-01-05" and rows[-1]["day"] == "2024-01-08"
    for row in rows:
        original = next(r for r in history if r["day"] == date.fromisoformat(row["day"]))
        assert D(row["cumulative_cash_additions"]) == original["cumulative_cash_additions"]
        assert D(row["returns_base"]) == original["returns_base"]


def test_total_uses_lifetime_cash_for_only_the_portfolios_in_each_days_nav(engine_db: None) -> None:
    pnl_service.rebuild(1, through=JAN[9])
    db.execute(
        "INSERT INTO portfolios (name, base_currency, reporting_start_date) VALUES ('Second', 'DKK', '2024-01-08')"
    )
    db.execute(
        "INSERT INTO portfolio_days (portfolio_id, day, base_currency, nav, positions_value, cash_value, nav_prev,"
        " flow, daily_pnl, daily_return_pct, unit_price, units, cumulative_return_pct, drawdown_pct) VALUES"
        " (2, '2024-01-02', 'DKK', 30000, 0, 30000, 0, 30000, 0, NULL, 100, 300, 0, 0),"
        " (2, '2024-01-08', 'DKK', 36000, 0, 36000, 30000, 0, 6000, 0.2, 120, 300, 0.2, 0),"
        " (2, '2024-01-09', 'DKK', 36500, 0, 36500, 36000, 500, 0, 0, 120, 304.166666666667, 0.2, 0)"
    )
    first = {r["day"]: r for r in pnl_service.portfolio_days(1)}
    second = {r["day"]: r for r in pnl_service.portfolio_days(2)}
    total = pnl_service.portfolio_days(None)
    for row in total:
        included = [first[row["day"]]]
        if row["day"] >= JAN[8]:
            included.append(second[row["day"]])
        assert row["cumulative_cash_additions"] == sum(r["cumulative_cash_additions"] for r in included)
        assert row["returns_base"] == sum(r["returns_base"] for r in included)
    entry = next(r for r in total if r["day"] == JAN[8])
    assert entry["cumulative_cash_additions"] == 41000
    assert pnl_service.portfolio_days(None, date_gte=JAN[9]) == total[-1:]
