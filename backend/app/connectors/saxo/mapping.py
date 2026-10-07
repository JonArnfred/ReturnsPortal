"""Pure mapping from Saxo DTOs to domain records. No I/O; unit-tested against recorded payloads.

Conventions established from real payloads (2026-09-18):
- Trades: ``Amount`` is signed (bought positive, sold negative); ``TradedValue`` is the cash effect
  in the instrument currency (buy negative). ``TradeType == "NotAvailable"`` marks zero-cash pairs
  that Saxo books for splits, mergers and ticker changes; they become ``corporate_action`` rows.
- Bookings: every cash movement. ``BkAmountType`` names the kind; ``Cash Amount`` rows are external
  deposits/withdrawals unless the symbol is ``CASHINTR`` (transfer between the client's own
  currency accounts, including FX conversions). ``Share Amount`` rows are the booked cash legs of
  trades and are folded into the trade row rather than emitted separately.
- Symbols look like ``ROKU:xnas``: ticker, colon, lowercase MIC.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal
from typing import Any

from app.connectors.saxo.dto import (
    SaxoAccount,
    SaxoBalance,
    SaxoBooking,
    SaxoExchange,
    SaxoInstrumentDetails,
    SaxoOrder,
    SaxoOrderActivity,
    SaxoPosition,
    SaxoTrade,
)
from app.domain.models import (
    CashSnapshotRow,
    ExchangeRecord,
    LedgerKind,
    LedgerRow,
    OrderRecord,
    OrderStatus,
    PositionSnapshotRow,
    SecurityKey,
    SecurityRecord,
)
from app.services.connection_service import BrokerAccount

BROKER = "saxo"
INTERNAL_TRANSFER_SYMBOL = "CASHINTR"
SHARE_AMOUNT = "Share Amount"

BOOKING_KINDS: dict[str, LedgerKind] = {
    "Commission": "commission",
    "Corporate Actions - Cash Dividends": "dividend",
    "Corporate Actions - Withholding Tax": "withholding_tax",
    "Corporate Actions - Fee": "fee",
    "Exchange Fee": "fee",
    "Exchange Subscription Fee": "fee",
    "Depository Charges": "fee",
    "Italian Financial Transaction Tax": "tax",
    "Withholding Tax ASK Account": "tax",
    "Interest": "interest",
    "Securities Lending Client Fee": "lending_income",
}


def split_symbol(symbol: str | None) -> tuple[str, str | None]:
    """``"ROKU:xnas"`` -> ``("ROKU", "XNAS")``. A symbol without a suffix keeps a null MIC."""
    if not symbol:
        return "", None
    ticker, _, suffix = symbol.partition(":")
    return ticker.strip(), suffix.strip().upper() or None


def security_key(uic: int, asset_type: str) -> SecurityKey:
    return SecurityKey(broker=BROKER, uic=uic, asset_type=asset_type)


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0 or numerator == 0:
        return None
    return numerator / denominator


def map_account(row: SaxoAccount, raw: dict[str, Any]) -> BrokerAccount:
    return BrokerAccount(
        account_key=row.account_key,
        account_id=row.account_id or None,
        currency=row.currency or None,
        account_type=row.account_type or None,
        active=row.active,
        raw=raw,
    )


def map_exchange(row: SaxoExchange, raw: dict[str, Any]) -> ExchangeRecord:
    return ExchangeRecord(
        exchange_id=row.exchange_id,
        mic=row.mic,
        iso_mic=row.iso_mic,
        operating_mic=row.operating_mic,
        name=row.name,
        country_code=row.country_code,
        currency=row.currency,
        timezone=str(row.time_zone) if row.time_zone is not None else None,
        raw=raw,
    )


def map_instrument(row: SaxoInstrumentDetails, raw: dict[str, Any]) -> SecurityRecord:
    ticker, mic = split_symbol(row.symbol)
    return SecurityRecord(
        key=security_key(row.uic, row.asset_type),
        symbol=row.symbol,
        ticker=ticker,
        mic=mic,
        name=row.description,
        currency=row.currency_code,
        exchange_id=row.exchange.exchange_id if row.exchange else None,
        raw=raw,
    )


def security_from_position(row: SaxoPosition, raw: dict[str, Any]) -> SecurityRecord:
    """Fallback security record when instrument details were not captured for a held position."""
    symbol = (row.display.symbol if row.display else None) or f"{row.base.uic}:"
    ticker, mic = split_symbol(symbol)
    return SecurityRecord(
        key=security_key(row.base.uic, row.base.asset_type),
        symbol=symbol,
        ticker=ticker or str(row.base.uic),
        mic=mic,
        name=row.display.description if row.display else None,
        currency=row.display.currency if row.display else None,
        exchange_id=row.exchange.exchange_id if row.exchange else None,
        raw=raw,
    )


def map_trade(
    trade: SaxoTrade,
    raw: dict[str, Any],
    *,
    base_currency: str,
    instrument_currency: str | None,
    share_booking: SaxoBooking | None,
    account_key: str | None,
) -> LedgerRow:
    """A trade becomes one ledger row carrying quantity, price and its booked cash leg.

    The cash leg comes from the linked ``Share Amount`` booking when Saxo provides one (that is the
    amount actually debited), otherwise from ``TradedValue``. Corporate-action pseudo-trades carry
    no cash.
    """
    is_corporate_action = trade.trade_type == "NotAvailable" and share_booking is None
    kind: LedgerKind = "corporate_action" if is_corporate_action else "trade"
    if share_booking is not None:
        currency = share_booking.currency
        amount_local = share_booking.amount
        amount_account = share_booking.amount_account_currency
        account_currency = share_booking.account_currency
        amount_base = share_booking.amount_client_currency
    else:
        currency = instrument_currency or trade.account_currency or base_currency
        amount_local = Decimal(0) if is_corporate_action else trade.traded_value
        amount_account = Decimal(0) if is_corporate_action else trade.booked_amount_account_currency
        account_currency = trade.account_currency
        amount_base = Decimal(0) if is_corporate_action else trade.booked_amount_client_currency
    return LedgerRow(
        broker_ref=f"trade:{trade.trade_id}",
        kind=kind,
        trade_date=trade.trade_date,
        value_date=trade.value_date,
        account_key=account_key,
        security=security_key(trade.uic, trade.asset_type),
        quantity=trade.amount,
        price=trade.price,
        currency=currency,
        amount_local=amount_local,
        account_currency=account_currency,
        amount_account=amount_account,
        base_currency=base_currency,
        amount_base=amount_base,
        fx_rate_base=_ratio(amount_base, amount_local),
        related_ref=f"booking:{share_booking.bk_amount_id}" if share_booking else None,
        description=trade.instrument_description or trade.instrument_symbol,
        source_endpoint="cs/v1/reports/trades",
        raw=raw,
    )


FILL_STATUSES = frozenset({"Fill", "FinalFill"})
EXECUTED_ENDPOINT = "cs/v1/audit/orderactivities"


def map_fill(
    activity: SaxoOrderActivity,
    raw: dict[str, Any],
    *,
    base_currency: str,
    instrument_currency: str | None,
    account_key: str | None,
    account_currency: str | None,
    fx_rate_base: Decimal | None,
    description: str | None,
) -> LedgerRow | None:
    """An executed fill from the order audit becomes a provisional trade row, so a trade shows up the
    moment it executes instead of when Saxo books it (usually the next morning).

    The cash leg is quantity times execution price, converted at the forward-filled ECB rate; the
    booked row that replaces it later carries Saxo's own conversion and the commission. None for
    events that are not fills or lack the fields a trade needs.
    """
    if activity.status not in FILL_STATUSES or activity.uic is None or activity.asset_type is None:
        return None
    price = activity.execution_price if activity.execution_price is not None else activity.average_price
    if activity.fill_amount is None or price is None or activity.activity_time is None or not activity.log_id:
        return None
    sign = Decimal(-1) if activity.buy_sell == "Sell" else Decimal(1)
    quantity = sign * activity.fill_amount
    amount_local = -quantity * price
    currency = instrument_currency or base_currency
    amount_base = None if fx_rate_base is None else amount_local * fx_rate_base
    if account_currency == currency:
        amount_account: Decimal | None = amount_local
    elif account_currency == base_currency:
        amount_account = amount_base
    else:
        amount_account = None
    return LedgerRow(
        broker_ref=f"fill:{activity.log_id}",
        kind="trade",
        trade_date=activity.activity_time.astimezone(UTC).date(),
        value_date=None,
        account_key=account_key,
        security=security_key(activity.uic, activity.asset_type),
        quantity=quantity,
        price=price,
        currency=currency,
        amount_local=amount_local,
        account_currency=account_currency,
        amount_account=amount_account,
        base_currency=base_currency,
        amount_base=amount_base,
        fx_rate_base=fx_rate_base,
        related_ref=f"order:{activity.order_id}",
        description=description,
        source_endpoint=EXECUTED_ENDPOINT,
        raw=raw,
    )


def booking_kind(booking: SaxoBooking) -> LedgerKind | None:
    """Ledger kind for a booking, or None when the booking is folded into a trade row."""
    if booking.bk_amount_type == SHARE_AMOUNT:
        return None
    if booking.bk_amount_type == "Cash Amount":
        if booking.instrument_symbol == INTERNAL_TRANSFER_SYMBOL:
            return "transfer"
        return "deposit" if booking.amount >= 0 else "withdrawal"
    return BOOKING_KINDS.get(booking.bk_amount_type, "other")


def map_booking(
    booking: SaxoBooking, raw: dict[str, Any], *, base_currency: str, account_key: str | None
) -> LedgerRow | None:
    kind = booking_kind(booking)
    if kind is None:
        return None
    security = (
        security_key(booking.uic, booking.asset_type)
        if booking.uic and booking.asset_type and booking.asset_type != "Cash"
        else None
    )
    return LedgerRow(
        broker_ref=f"booking:{booking.bk_amount_id}",
        kind=kind,
        trade_date=booking.date,
        value_date=booking.value_date,
        account_key=account_key,
        security=security,
        quantity=None,
        price=None,
        currency=booking.currency,
        amount_local=booking.amount,
        account_currency=booking.account_currency,
        amount_account=booking.amount_account_currency,
        base_currency=base_currency,
        amount_base=booking.amount_client_currency,
        fx_rate_base=_ratio(booking.amount_client_currency, booking.amount),
        related_ref=f"trade:{booking.related_trade_id}" if booking.related_trade_id not in (None, "0") else None,
        description=booking.instrument_description or booking.bk_amount_type,
        source_endpoint="cs/v1/reports/bookings",
        raw=raw,
    )


def map_position(row: SaxoPosition, raw: dict[str, Any], *, snapshot_date: Any, fetched_at: Any) -> PositionSnapshotRow:
    view = row.view
    return PositionSnapshotRow(
        snapshot_date=snapshot_date,
        account_key=row.base.account_key,
        broker_position_id=row.position_id,
        security=security_key(row.base.uic, row.base.asset_type),
        quantity=row.base.amount,
        open_price=row.base.open_price,
        current_price=view.current_price if view else None,
        currency=(row.display.currency if row.display else None) or (view.exposure_currency if view else None),
        market_value_local=view.market_value if view else None,
        market_value_base=view.market_value_in_base_currency if view else None,
        fx_rate_base=view.conversion_rate_current if view else None,
        raw=raw,
        fetched_at=fetched_at,
    )


def map_balance(
    row: SaxoBalance, raw: dict[str, Any], *, account_key: str, snapshot_date: Any, fetched_at: Any
) -> CashSnapshotRow:
    return CashSnapshotRow(
        snapshot_date=snapshot_date,
        account_key=account_key,
        currency=row.currency,
        cash_balance=row.cash_balance,
        total_value=row.total_value,
        raw=raw,
        fetched_at=fetched_at,
    )


ORDER_STATUSES: dict[str, OrderStatus] = {
    # Live on the broker's book, including off-book overnight and partially filled.
    "placed": "working",
    "requested": "working",
    "working": "working",
    "changed": "working",
    "parked": "working",
    "doneforday": "working",
    "fill": "working",
    "partiallyfilled": "working",
    "finalfill": "filled",
    "filled": "filled",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "expired": "expired",
    "rejected": "rejected",
}


def normalize_order_status(value: str | None) -> OrderStatus:
    """Collapse Saxo's order and order-activity statuses into the app's vocabulary.

    Exact matches come from live data (see ``SaxoOrderActivity``); the keyword fallback keeps an
    unseen wording from landing in ``other`` when its meaning is obvious.
    """
    key = "".join(ch for ch in (value or "").lower() if ch.isalpha())
    if key in ORDER_STATUSES:
        return ORDER_STATUSES[key]
    for word, status in (("cancel", "cancelled"), ("expire", "expired"), ("reject", "rejected")):
        if word in key:
            return status  # type: ignore[return-value]
    if "partial" in key:
        return "working"
    if "fill" in key:
        return "filled"
    if any(word in key for word in ("work", "placed", "park", "pending", "open")):
        return "working"
    return "other"


def _buy_sell(value: str | None) -> Any:
    key = (value or "").strip().lower()
    return key if key in ("buy", "sell") else None


def map_open_order(row: SaxoOrder, raw: dict[str, Any], *, fetched_at: Any) -> OrderRecord:
    """A working order as the broker lists it right now."""
    return OrderRecord(
        broker_order_id=row.order_id,
        account_key=row.account_key,
        security=security_key(row.uic, row.asset_type) if row.uic and row.asset_type else None,
        instrument_symbol=row.display.symbol if row.display else None,
        instrument_name=row.display.description if row.display else None,
        status="working",
        broker_status=row.status,
        is_open=True,
        buy_sell=_buy_sell(row.buy_sell),
        order_type=row.open_order_type or row.order_type,
        duration=row.duration.duration_type if row.duration else None,
        quantity=row.amount,
        filled_quantity=row.filled_amount,
        price=row.price,
        average_fill_price=None,
        currency=row.display.currency if row.display else None,
        placed_at=row.order_time,
        last_activity_at=row.order_time or fetched_at,
        expires_at=row.duration.expiration_date_time if row.duration else None,
        order_relation=row.order_relation,
        source_endpoint="port/v1/orders/me",
        raw=raw,
        fetched_at=fetched_at,
    )


def order_activity_status(row: SaxoOrderActivity) -> OrderStatus:
    """A rejected request is a rejected order; a day order that is done for the day has expired."""
    if (row.sub_status or "").lower() == "rejected":
        return "rejected"
    status = normalize_order_status(row.status)
    duration = row.duration.duration_type if row.duration else None
    if (row.status or "").lower() == "doneforday" and duration == "DayOrder":
        return "expired"
    return status


def map_order_activity(
    row: SaxoOrderActivity, raw: dict[str, Any], *, account_key: str | None, fetched_at: Any
) -> OrderRecord:
    """One order event; the order's history is folded from these by ``order_service.merge_orders``."""
    status = order_activity_status(row)
    broker_status = f"{row.status}/{row.sub_status}" if row.sub_status and row.sub_status != "Confirmed" else row.status
    return OrderRecord(
        broker_order_id=row.order_id,
        account_key=account_key,
        security=security_key(row.uic, row.asset_type) if row.uic and row.asset_type else None,
        instrument_symbol=None,
        instrument_name=None,
        status=status,
        broker_status=broker_status,
        is_open=False,
        buy_sell=_buy_sell(row.buy_sell),
        order_type=row.order_type,
        duration=row.duration.duration_type if row.duration else None,
        quantity=row.amount,
        filled_quantity=row.filled_amount,
        price=row.price,
        average_fill_price=row.average_price if row.average_price is not None else row.execution_price,
        currency=None,
        placed_at=row.activity_time if (row.status or "").lower() == "placed" else None,
        last_activity_at=row.activity_time,
        expires_at=row.duration.expiration_date_time if row.duration else None,
        order_relation=row.order_relation,
        source_endpoint="cs/v1/audit/orderactivities",
        raw=raw,
        fetched_at=fetched_at,
    )


def security_from_order(order: OrderRecord) -> SecurityRecord | None:
    """Fallback security record for an order on an instrument that was never traded or held."""
    if order.security is None:
        return None
    symbol = order.instrument_symbol or f"{order.security.uic}:"
    ticker, mic = split_symbol(symbol)
    return SecurityRecord(
        key=order.security,
        symbol=symbol,
        ticker=ticker or str(order.security.uic),
        mic=mic,
        name=order.instrument_name,
        currency=order.currency,
        exchange_id=None,
        raw={"source": "order", "row": order.raw},
    )
