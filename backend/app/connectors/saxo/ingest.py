"""Map captured Saxo payloads into securities, ledger rows and snapshots, then reconcile.

Reads only from ``broker_raw_payloads``; never calls Saxo. Safe to rerun: every write is an upsert
keyed on the broker's own identifiers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, timedelta
from typing import Any

import app.services.connection_service as connections
from app.connectors.saxo import mapping
from app.connectors.saxo.dto import (
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
    LedgerRow,
    OrderRecord,
    PositionSnapshotRow,
    SecurityKey,
    SecurityRecord,
)
from app.services import fx_service, order_service, position_service, settings_service
from app.services import ledger_service as ledger
from app.services.snapshot_reconcile import CASH_TOLERANCE, QUANTITY_TOLERANCE, reconcile

__all__ = ["CASH_TOLERANCE", "QUANTITY_TOLERANCE", "IngestReport", "ingest", "is_booked", "reconcile"]

logger = logging.getLogger("returns-portal.saxo")


@dataclass
class IngestReport:
    connection_id: int
    portfolio_id: int = 0
    exchanges: int = 0
    securities: int = 0
    trades: int = 0
    executed_fills: int = 0
    bookings_mapped: int = 0
    bookings_folded: int = 0
    ledger_rows: int = 0
    positions_rebuilt: int = 0
    positions: int = 0
    cash_rows: int = 0
    orders: int = 0
    open_orders: int = 0
    warnings: list[str] = field(default_factory=list)
    reconciliation: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__


def _data_rows(payloads: list[connections.RawPayload]) -> list[tuple[dict[str, Any], connections.RawPayload]]:
    rows: list[tuple[dict[str, Any], connections.RawPayload]] = []
    for payload in payloads:
        body = payload.payload
        if isinstance(body, dict) and isinstance(body.get("Data"), list):
            rows.extend((row, payload) for row in body["Data"] if isinstance(row, dict))
        elif isinstance(body, dict):
            rows.append((body, payload))
    return rows


def ingest(connection_id: int) -> IngestReport:
    report = IngestReport(connection_id=connection_id)
    connection = connections.get_connection(connection_id)
    if connection is None:
        raise ValueError(f"connection {connection_id} does not exist")
    base_currency = settings_service.reporting_currency()
    if connection.base_currency and connection.base_currency != base_currency:
        # Saxo's booked client-currency amounts are taken as base amounts; converting them into another
        # reporting currency is not implemented (the IBKR connector shows how, see BaseConversion).
        raise RuntimeError(
            f"Saxo client currency {connection.base_currency} differs from the reporting currency {base_currency}"
        )
    report.portfolio_id = ledger.upsert_portfolio(
        connection_id, name=f"Saxo {connection.client_name or ''}".strip(), base_currency=base_currency
    )
    accounts = connections.list_accounts(connection_id)
    account_key_by_id = {account.account_id: account.account_key for account in accounts if account.account_id}

    # Reference data first, so ledger rows can point at securities.
    exchanges = [
        mapping.map_exchange(SaxoExchange.model_validate(row), row)
        for row, _ in _data_rows(connections.raw_payloads(connection_id, "ref/v1/exchanges", latest_run_only=True))
    ]
    report.exchanges = ledger.upsert_exchanges(exchanges)

    securities: dict[SecurityKey, SecurityRecord] = {}
    for row, _ in _data_rows(
        connections.raw_payloads(connection_id, "ref/v1/instruments/details", latest_run_only=False)
    ):
        record = mapping.map_instrument(SaxoInstrumentDetails.model_validate(row), row)
        securities[record.key] = record

    positions_raw = _data_rows(connections.raw_payloads(connection_id, "port/v1/positions", latest_run_only=True))
    positions = [(SaxoPosition.model_validate(row), row, payload) for row, payload in positions_raw]
    for position, row, _ in positions:
        key = mapping.security_key(position.base.uic, position.base.asset_type)
        securities.setdefault(key, mapping.security_from_position(position, row))

    open_orders = [
        mapping.map_open_order(SaxoOrder.model_validate(row), row, fetched_at=payload.fetched_at.astimezone(UTC))
        for row, payload in _data_rows(
            connections.raw_payloads(connection_id, "port/v1/orders/me", latest_run_only=True)
        )
    ]
    activities: list[OrderRecord] = []
    activity_rows: list[tuple[SaxoOrderActivity, dict[str, Any]]] = []
    for row, payload in _data_rows(
        connections.raw_payloads(connection_id, "cs/v1/audit/orderactivities", latest_run_only=False)
    ):
        activity = SaxoOrderActivity.model_validate(row)
        activity_rows.append((activity, row))
        activities.append(
            mapping.map_order_activity(
                activity,
                row,
                account_key=account_key_by_id.get(activity.account_id or ""),
                fetched_at=payload.fetched_at.astimezone(UTC),
            )
        )
    orders = order_service.merge_orders(activities, open_orders)
    for order in orders:
        fallback = mapping.security_from_order(order)
        if fallback is not None:
            securities.setdefault(fallback.key, fallback)

    trades_by_id: dict[str, tuple[SaxoTrade, dict[str, Any]]] = {}
    for row, _ in _data_rows(connections.raw_payloads(connection_id, "cs/v1/reports/trades", latest_run_only=False)):
        trade = SaxoTrade.model_validate(row)
        trades_by_id[trade.trade_id] = (trade, row)
    bookings_by_id: dict[str, tuple[SaxoBooking, dict[str, Any]]] = {}
    for row, _ in _data_rows(connections.raw_payloads(connection_id, "cs/v1/reports/bookings", latest_run_only=False)):
        booking = SaxoBooking.model_validate(row)
        bookings_by_id[booking.bk_amount_id] = (booking, row)
    share_bookings = {
        booking.related_trade_id: booking
        for booking, _ in bookings_by_id.values()
        if booking.bk_amount_type == mapping.SHARE_AMOUNT and booking.related_trade_id
    }

    for trade, row in trades_by_id.values():
        key = mapping.security_key(trade.uic, trade.asset_type)
        if key not in securities:
            share = share_bookings.get(trade.trade_id)
            ticker, mic = mapping.split_symbol(trade.instrument_symbol)
            securities[key] = SecurityRecord(
                key=key,
                symbol=trade.instrument_symbol or str(trade.uic),
                ticker=ticker or str(trade.uic),
                mic=mic,
                name=trade.instrument_description,
                currency=share.currency if share else None,
                exchange_id=None,
                raw={"source": "trade", "row": row},
            )
            report.warnings.append(f"no instrument details for {key.uic}/{key.asset_type}; derived from trade row")
    report.securities = ledger.upsert_securities(list(securities.values()))
    ids = ledger.security_ids(mapping.BROKER)
    currencies = {key: record.currency for key, record in securities.items()}

    rows: list[LedgerRow] = []
    for trade, row in trades_by_id.values():
        share = share_bookings.get(trade.trade_id)
        rows.append(
            mapping.map_trade(
                trade,
                row,
                base_currency=base_currency,
                instrument_currency=currencies.get(mapping.security_key(trade.uic, trade.asset_type)),
                share_booking=share,
                account_key=account_key_by_id.get(trade.account_id or ""),
            )
        )
    report.trades = len(rows)
    # Executed but not yet booked: fills from the order audit stand in for the trade until Saxo's
    # report carries the booked row for the same order, which then supersedes them.
    booked_orders = {(trade.order_id, trade.trade_date) for trade, _ in trades_by_id.values() if trade.order_id}
    account_currency_by_key = {account.account_key: account.currency for account in accounts}
    names = {key: record.name for key, record in securities.items()}
    for activity, row in activity_rows:
        if activity.status not in mapping.FILL_STATUSES or activity.uic is None or activity.asset_type is None:
            continue
        if activity.activity_time is None or is_booked(activity.order_id, activity.activity_time.date(), booked_orders):
            continue
        key = mapping.security_key(activity.uic, activity.asset_type)
        if key not in ids:
            report.warnings.append(f"fill {activity.log_id} references unknown security {activity.uic}")
            continue
        currency = currencies.get(key) or base_currency
        fill_day = activity.activity_time.astimezone(UTC).date()
        fx_rate = fx_service.rate_on(base_currency, currency, fill_day)
        if fx_rate is None:
            report.warnings.append(
                f"no {currency} rate for fill {activity.log_id} on {fill_day}; base amount left empty"
            )
        account_key = account_key_by_id.get(activity.account_id or "")
        mapped = mapping.map_fill(
            activity,
            row,
            base_currency=base_currency,
            instrument_currency=currency,
            account_key=account_key,
            account_currency=account_currency_by_key.get(account_key or ""),
            fx_rate_base=fx_rate,
            description=names.get(key),
        )
        if mapped is not None:
            rows.append(mapped)
            report.executed_fills += 1
    for booking, row in bookings_by_id.values():
        mapped = mapping.map_booking(
            booking, row, base_currency=base_currency, account_key=account_key_by_id.get(booking.account_id or "")
        )
        if mapped is None:
            report.bookings_folded += 1
            if booking.related_trade_id not in trades_by_id:
                report.warnings.append(f"share booking {booking.bk_amount_id} has no matching trade")
            continue
        if mapped.security and mapped.security not in ids:
            report.warnings.append(f"booking {booking.bk_amount_id} references unknown security {mapped.security.uic}")
            mapped = mapped.model_copy(update={"security": None})
        rows.append(mapped)
        report.bookings_mapped += 1
    report.ledger_rows = ledger.upsert_ledger(connection_id, report.portfolio_id, rows, ids)
    ledger.delete_superseded_fills(connection_id)
    report.positions_rebuilt = int(position_service.rebuild(report.portfolio_id).get("position_rows", 0))

    snapshot_rows: list[PositionSnapshotRow] = []
    for position, row, payload in positions:
        fetched = payload.fetched_at.astimezone(UTC)
        snapshot_rows.append(mapping.map_position(position, row, snapshot_date=fetched.date(), fetched_at=fetched))
    report.positions = ledger.upsert_position_snapshots(connection_id, report.portfolio_id, snapshot_rows, ids)

    cash_rows: list[CashSnapshotRow] = []
    for row, payload in _data_rows(connections.raw_payloads(connection_id, "port/v1/balances", latest_run_only=True)):
        fetched = payload.fetched_at.astimezone(UTC)
        cash_rows.append(
            mapping.map_balance(
                SaxoBalance.model_validate(row),
                row,
                account_key=str(payload.params.get("AccountKey") or ""),
                snapshot_date=fetched.date(),
                fetched_at=fetched,
            )
        )
    report.cash_rows = ledger.upsert_cash_snapshots(connection_id, report.portfolio_id, cash_rows)

    report.orders = ledger.upsert_orders(connection_id, report.portfolio_id, orders, ids)
    report.open_orders = sum(1 for order in orders if order.is_open)

    report.reconciliation = reconcile(connection_id)
    return report


BOOKING_SLACK = timedelta(days=1)


def is_booked(order_id: str, fill_day: date, booked_orders: set[tuple[str, date]]) -> bool:
    """Whether Saxo's trades report already carries this order's fill; the booked trade date may sit a
    day off the execution time, so a day of slack is allowed either way."""
    return any(
        booked_order == order_id and abs(booked_day - fill_day) <= BOOKING_SLACK
        for booked_order, booked_day in booked_orders
    )
