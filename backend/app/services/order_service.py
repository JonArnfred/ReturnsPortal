"""Orders: fold broker order events into one row per order, and the read model for the Orders page."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from app import db
from app.domain.models import OrderRecord
from app.services import ledger_sql as sql

# Fields a later event inherits from earlier ones when it does not carry them itself.
_INHERITED = (
    "account_key",
    "security",
    "instrument_symbol",
    "instrument_name",
    "buy_sell",
    "order_type",
    "duration",
    "quantity",
    "price",
    "average_fill_price",
    "currency",
    "expires_at",
    "order_relation",
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _inherit(later: OrderRecord, earlier: OrderRecord) -> OrderRecord:
    update: dict[str, Any] = {name: getattr(earlier, name) for name in _INHERITED if getattr(later, name) is None}
    update["placed_at"] = earlier.placed_at or later.placed_at or earlier.last_activity_at
    filled = [value for value in (earlier.filled_quantity, later.filled_quantity) if value is not None]
    update["filled_quantity"] = max(filled) if filled else None
    return later.model_copy(update=update)


def merge_orders(
    activities: list[OrderRecord], open_orders: list[OrderRecord], as_of: date | None = None
) -> list[OrderRecord]:
    """One record per broker order id.

    Events are applied oldest first, so the latest event decides the status while earlier events
    supply the placement time and any field the latest lacks. The broker's working-orders list is
    applied last: those orders are open whatever the audit log says, and an order absent from that
    list is not open even if its last known event says it was. Saxo does not always log the expiry
    of a day order, so a day order that is off the book after its day is reported as expired.
    """
    today = as_of or datetime.now(UTC).date()
    merged: dict[str, OrderRecord] = {}
    seen: set[tuple[str, datetime | None, str | None]] = set()
    for event in sorted(activities, key=lambda row: (row.last_activity_at or _EPOCH, row.fetched_at)):
        signature = (event.broker_order_id, event.last_activity_at, event.broker_status)
        if signature in seen:
            continue  # the same window is captured again on every sync
        seen.add(signature)
        previous = merged.get(event.broker_order_id)
        merged[event.broker_order_id] = (
            _inherit(event, previous)
            if previous
            else event.model_copy(update={"placed_at": event.placed_at or event.last_activity_at})
        )
    for order in open_orders:
        previous = merged.get(order.broker_order_id)
        merged[order.broker_order_id] = _inherit(order, previous) if previous else order
    for order_id, order in merged.items():
        last = order.last_activity_at
        if (
            order.status == "working"
            and not order.is_open
            and order.duration == "DayOrder"
            and last
            and last.date() < today
        ):
            merged[order_id] = order.model_copy(update={"status": "expired"})
    return sorted(merged.values(), key=lambda row: (row.placed_at or _EPOCH, row.broker_order_id))


def list_orders() -> list[dict[str, Any]]:
    rows = db.select(sql.SELECT_ORDERS)
    for row in rows:
        ticker, mic = row.pop("ticker"), row.pop("mic")
        row["full_ticker"] = (f"{ticker}:{mic}" if mic else ticker) if ticker else None
        account_id, account_currency = row.pop("account_id"), row.pop("account_currency")
        row["account_label"] = f"{account_id} ({account_currency})" if account_id and account_currency else account_id
    return rows
