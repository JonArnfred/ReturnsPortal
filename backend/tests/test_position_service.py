from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.services import position_service


def row(kind: str, day: str, quantity: str | None, price: str | None, **extra: Any) -> dict[str, Any]:
    base = {
        "kind": kind,
        "trade_date": date.fromisoformat(day),
        "quantity": Decimal(quantity) if quantity is not None else None,
        "price": Decimal(price) if price is not None else None,
        "currency": "USD",
        "amount_local": Decimal("0"),
        "amount_base": Decimal("0"),
    }
    base.update(extra)
    return base


def test_annualized_guards() -> None:
    assert position_service._annualized(None, Decimal(100), Decimal(365)) is None
    assert position_service._annualized(Decimal("-1.5"), Decimal(100), Decimal(365)) is None
    assert position_service._annualized(Decimal("0.1"), Decimal(3), Decimal(365)) is None
    value = position_service._annualized(Decimal("0.1"), Decimal(365), Decimal(365))
    assert value is not None and value.quantize(Decimal("0.0001")) == Decimal("0.1000")


def test_series_and_trades_are_on_the_split_adjusted_basis() -> None:
    rows = [  # basis_factor as rebuild_positions stores it: the booked split scales the earlier trade
        row("trade", "2021-05-03", "1", "806", basis_factor=Decimal("10")),
        row("corporate_action", "2021-06-17", "-1", "806", basis_factor=Decimal("1")),
        row("corporate_action", "2021-06-17", "10", "80.6", basis_factor=Decimal("1")),
        row("trade", "2021-07-01", "5", "90", basis_factor=Decimal("1")),
    ]
    prices = [
        {"price_date": date(2021, 5, 1), "close": Decimal("80")},  # before the first trade: skipped
        {"price_date": date(2021, 5, 3), "close": Decimal("80.6")},
        {"price_date": date(2021, 6, 16), "close": Decimal("82")},
        {"price_date": date(2021, 6, 17), "close": Decimal("83")},
        {"price_date": date(2021, 7, 1), "close": Decimal("90")},
    ]
    series = position_service.position_series(rows, prices)
    assert [(point["date"], point["quantity"], point["market_value"]) for point in series] == [
        (date(2021, 5, 3), Decimal("10"), Decimal("806.0")),
        (date(2021, 6, 16), Decimal("10"), Decimal("820")),
        (date(2021, 6, 17), Decimal("10"), Decimal("830")),
        (date(2021, 7, 1), Decimal("15"), Decimal("1350")),
    ]
    trades = position_service.position_trades(rows)
    assert [(trade["kind"], trade["quantity"], trade["adjusted_price"]) for trade in trades] == [
        ("buy", Decimal("1"), Decimal("80.6")),
        ("corporate_action", Decimal("9"), None),
        ("buy", Decimal("5"), Decimal("90")),
    ]


def test_inferred_split_factor_scales_series_and_prices() -> None:
    rows = [
        row("trade", "2021-01-07", "1", "1769.1", basis_factor=Decimal("20")),
        row("trade", "2021-07-20", "-1", "2515.6", basis_factor=Decimal("20")),
    ]
    prices = [
        {"price_date": date(2021, 1, 7), "close": Decimal("88.717")},
        {"price_date": date(2021, 7, 20), "close": Decimal("126.2")},
    ]
    series = position_service.position_series(rows, prices)
    assert [(point["quantity"], point["market_value"]) for point in series] == [
        (Decimal("20"), Decimal("1774.340")),
        (Decimal("0"), Decimal("0")),
    ]
    assert [trade["adjusted_price"] for trade in position_service.position_trades(rows)] == [
        Decimal("88.455"),
        Decimal("125.78"),
    ]


def test_ticker_change_legs_are_not_shown_as_trades() -> None:
    rows = [
        row("trade", "2021-02-08", "70", "13.7"),
        row("corporate_action", "2021-08-12", "-70", "10"),
        row("corporate_action", "2021-08-12", "70", "10"),
    ]
    assert [trade["kind"] for trade in position_service.position_trades(rows)] == ["buy"]


def test_returns_block_identity() -> None:
    block = position_service._returns_block(
        "USD",
        invested=Decimal("1002"),
        buy_cash=Decimal("1000"),
        sell_cash=Decimal("1200"),
        value=Decimal("0"),
        dividends=Decimal("10"),
        costs=Decimal("-2"),
        days=Decimal("153"),
        months=Decimal("5"),
    )
    assert block["total_cost"] == Decimal("-1000") and block["total_revenue"] == Decimal("1200")
    assert block["return_amount"] == Decimal("208")
    assert block["roi_pct"] == Decimal("208") / Decimal("1002")


def test_mark_values_use_the_broker_mark_for_open_positions_only() -> None:
    closed = {
        "closed": date(2024, 1, 1),
        "quantity": Decimal("0"),
        "current_price": Decimal("5"),
        "mark_value_base": None,
        "fx_rate_base": None,
    }
    assert position_service._mark_values(closed) == (None, Decimal(0), Decimal(0))
    marked = {
        "closed": None,
        "quantity": Decimal("10"),
        "current_price": Decimal("5"),
        "mark_value_base": Decimal("350"),
        "fx_rate_base": Decimal("7"),
    }
    assert position_service._mark_values(marked) == (Decimal("5"), Decimal("50"), Decimal("350"))
    derived = {
        "closed": None,
        "quantity": Decimal("10"),
        "current_price": Decimal("5"),
        "mark_value_base": None,
        "fx_rate_base": Decimal("7"),
    }
    assert position_service._mark_values(derived) == (Decimal("5"), Decimal("50"), Decimal("350"))
    unmarked = {
        "closed": None,
        "quantity": Decimal("10"),
        "current_price": None,
        "mark_value_base": None,
        "fx_rate_base": None,
    }
    assert position_service._mark_values(unmarked) == (None, None, None)


def test_mark_values_prefer_a_newer_engine_close_for_the_same_quantity() -> None:
    lagging = {
        "closed": None,
        "quantity": Decimal("10"),
        "current_price": Decimal("5"),
        "mark_value_base": Decimal("350"),
        "fx_rate_base": Decimal("7"),
        "mark_date": date(2026, 10, 2),
        "engine_quantity": Decimal("10"),
        "engine_price": Decimal("6"),
        "engine_price_date": date(2026, 10, 7),
        "engine_value_local": Decimal("60"),
        "engine_value_base": Decimal("426"),
    }
    assert position_service._mark_values(lagging) == (Decimal("6"), Decimal("60"), Decimal("426"))
    assert position_service._valuation_date(lagging) == date(2026, 10, 7)
    same_day = {**lagging, "mark_date": date(2026, 10, 7)}
    assert position_service._mark_values(same_day) == (Decimal("5"), Decimal("50"), Decimal("350"))
    rebuild_pending = {**lagging, "engine_quantity": Decimal("8")}
    assert position_service._mark_values(rebuild_pending) == (Decimal("5"), Decimal("50"), Decimal("350"))
    absent_from_snapshot = {**lagging, "mark_date": None, "current_price": None, "mark_value_base": None}
    assert position_service._mark_values(absent_from_snapshot) == (Decimal("6"), Decimal("60"), Decimal("426"))
