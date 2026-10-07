"""Order mapping and folding, with rows shaped like live Saxo payloads captured on 2026-09-19."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.connectors.saxo import mapping
from app.connectors.saxo.dto import SaxoOrder, SaxoOrderActivity
from app.services import order_service

FETCHED = datetime(2026, 9, 19, 6, 0, tzinfo=UTC)

OPEN_ORDER: dict[str, Any] = {
    "AccountId": "ACC1",
    "AccountKey": "AK1",
    "Amount": 3.0,
    "AssetType": "Stock",
    "BuySell": "Sell",
    "CurrentPrice": 1648.43,
    "DisplayAndFormat": {
        "Currency": "USD",
        "Decimals": 2,
        "Description": "Widget Systems Inc.",
        "Symbol": "WIDG:xnys",
    },
    "Duration": {"DurationType": "GoodTillCancel"},
    "Exchange": {"Description": "New York Stock Exchange", "ExchangeId": "NYSE"},
    "OpenOrderType": "Limit",
    "OrderAmountType": "Quantity",
    "OrderId": "O-1",
    "OrderRelation": "StandAlone",
    "OrderTime": "2026-09-18T11:03:39.890314Z",
    "Price": 2000.0,
    "Status": "Working",
    "Uic": 1000002,
}


def activity(
    status: str, time: str, order_id: str = "O-2", sub_status: str = "Confirmed", **extra: Any
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "AccountId": "ACC1",
        "ActivityTime": time,
        "Amount": 30.0,
        "AssetType": "Etf",
        "BuySell": "Sell",
        "Duration": {"DurationType": "GoodTillCancel"},
        "OrderId": order_id,
        "OrderRelation": "StandAlone",
        "OrderType": "Limit",
        "Price": 84.0,
        "Status": status,
        "SubStatus": sub_status,
        "Uic": 39343,
    }
    row.update(extra)
    return row


def map_activity(row: dict[str, Any]) -> Any:
    return mapping.map_order_activity(SaxoOrderActivity.model_validate(row), row, account_key="AK1", fetched_at=FETCHED)


def test_open_order_maps_symbol_type_and_time() -> None:
    order = mapping.map_open_order(SaxoOrder.model_validate(OPEN_ORDER), OPEN_ORDER, fetched_at=FETCHED)
    assert order.status == "working" and order.is_open and order.broker_status == "Working"
    assert order.buy_sell == "sell" and order.order_type == "Limit" and order.duration == "GoodTillCancel"
    assert order.quantity == Decimal("3") and order.price == Decimal("2000") and order.currency == "USD"
    assert order.instrument_symbol == "WIDG:xnys" and order.instrument_name == "Widget Systems Inc."
    assert order.security is not None and (order.security.uic, order.security.asset_type) == (1000002, "Stock")
    assert order.placed_at == datetime(2026, 9, 18, 11, 3, 39, 890314, tzinfo=UTC)
    fallback = mapping.security_from_order(order)
    assert fallback is not None and (fallback.ticker, fallback.mic, fallback.currency) == ("WIDG", "XNYS", "USD")


def test_status_vocabulary() -> None:
    assert [mapping.normalize_order_status(s) for s in ("Placed", "Working", "Changed", "DoneForDay", "Fill")] == [
        "working"
    ] * 5
    assert mapping.normalize_order_status("FinalFill") == "filled"
    assert mapping.normalize_order_status("Cancelled") == "cancelled"
    assert mapping.normalize_order_status("Expired") == "expired"
    assert mapping.normalize_order_status("SomethingNew") == "other"
    rejected = map_activity(activity("Placed", "2026-01-07T12:37:50Z", sub_status="Rejected"))
    assert rejected.status == "rejected" and rejected.broker_status == "Placed/Rejected"
    day_order = map_activity(activity("DoneForDay", "2026-01-07T16:00:00Z", Duration={"DurationType": "DayOrder"}))
    assert day_order.status == "expired"


def test_merge_folds_a_lifecycle_into_one_filled_order() -> None:
    events = [
        activity("Placed", "2026-01-02T07:51:34.000Z", sub_status="Requested"),
        activity("Placed", "2026-01-02T07:51:34.100Z"),
        activity("Working", "2026-01-02T07:51:34.620Z"),
        activity("DoneForDay", "2026-01-02T16:36:12.716Z"),
        activity("Working", "2026-01-05T07:50:39.895Z"),
        activity("Fill", "2026-01-05T14:00:00.000Z", FilledAmount=10.0, FillAmount=10.0, AveragePrice=84.0),
        activity("FinalFill", "2026-01-05T14:30:29.123Z", FilledAmount=30.0, FillAmount=20.0, AveragePrice=84.0),
    ]
    # Captured twice (two syncs of the same window): identical events must not double up.
    [order] = order_service.merge_orders([map_activity(row) for row in events + events], [])
    assert order.status == "filled" and not order.is_open and order.broker_status == "FinalFill"
    assert order.placed_at == datetime(2026, 1, 2, 7, 51, 34, tzinfo=UTC)
    assert order.last_activity_at == datetime(2026, 1, 5, 14, 30, 29, 123000, tzinfo=UTC)
    assert order.filled_quantity == Decimal("30") and order.average_fill_price == Decimal("84")
    assert order.quantity == Decimal("30") and order.account_key == "AK1" and order.buy_sell == "sell"


def test_merge_lets_the_open_list_decide_what_is_outstanding() -> None:
    stale = [map_activity(activity("Working", "2026-09-17T08:00:00Z", order_id="O-9"))]
    live_events = [
        map_activity(
            activity("Placed", "2026-09-18T11:03:39Z", order_id="O-1", Uic=1000002, AssetType="Stock", Amount=3.0)
        ),
        map_activity(
            activity("Working", "2026-09-18T11:03:40Z", order_id="O-1", Uic=1000002, AssetType="Stock", Amount=3.0)
        ),
    ]
    open_order = mapping.map_open_order(SaxoOrder.model_validate(OPEN_ORDER), OPEN_ORDER, fetched_at=FETCHED)
    merged = {row.broker_order_id: row for row in order_service.merge_orders(stale + live_events, [open_order])}
    assert merged["O-1"].is_open and merged["O-1"].instrument_symbol == "WIDG:xnys"
    assert merged["O-1"].placed_at == datetime(2026, 9, 18, 11, 3, 39, tzinfo=UTC)  # first Placed event wins
    assert (
        merged["O-9"].status == "working" and not merged["O-9"].is_open
    )  # gone from the book, no final event captured


def test_day_order_off_the_book_after_its_day_is_expired() -> None:
    old_day = map_activity(
        activity("Working", "2024-10-07T08:00:00Z", order_id="O-5", Duration={"DurationType": "DayOrder"})
    )
    same_day = map_activity(
        activity("Working", "2026-09-19T08:00:00Z", order_id="O-6", Duration={"DurationType": "DayOrder"})
    )
    gtc = map_activity(activity("Working", "2025-03-18T08:00:00Z", order_id="O-7"))
    merged = {
        row.broker_order_id: row
        for row in order_service.merge_orders([old_day, same_day, gtc], [], as_of=date(2026, 9, 19))
    }
    assert merged["O-5"].status == "expired" and merged["O-5"].broker_status == "Working"
    assert merged["O-6"].status == "working"  # still today: the broker may simply not have listed it yet
    assert merged["O-7"].status == "working"  # good-till-cancel: no expiry to infer
