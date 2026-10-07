"""Persistence for securities, portfolios, ledger rows, and snapshots (explicit SQL, bulk upserts)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app import db
from app.domain.models import (
    CashSnapshotRow,
    ExchangeRecord,
    LedgerRow,
    OrderRecord,
    PositionSnapshotRow,
    SecurityKey,
    SecurityRecord,
)
from app.services import ledger_sql as sql


def upsert_portfolio(connection_id: int, name: str, base_currency: str) -> int:
    row = db.select_one(
        sql.UPSERT_PORTFOLIO, {"connection_id": connection_id, "name": name, "base_currency": base_currency}
    )
    assert row is not None
    return int(row["id"])


def upsert_exchanges(rows: list[ExchangeRecord]) -> int:
    return db.upsert_many(
        "exchanges",
        [
            {
                "exchange_id": row.exchange_id,
                "mic": row.mic,
                "iso_mic": row.iso_mic,
                "operating_mic": row.operating_mic,
                "name": row.name,
                "country_code": row.country_code,
                "currency": row.currency,
                "timezone": row.timezone,
                "raw": db.Jsonb(row.raw),
            }
            for row in rows
        ],
        conflict_columns=("exchange_id",),
    )


def upsert_securities(rows: list[SecurityRecord]) -> int:
    return db.upsert_many(
        "securities",
        [
            {
                "broker": row.key.broker,
                "uic": row.key.uic,
                "asset_type": row.key.asset_type,
                "symbol": row.symbol,
                "ticker": row.ticker,
                "mic": row.mic,
                "name": row.name,
                "currency": row.currency,
                "exchange_id": row.exchange_id,
                "isin": row.isin,
                "raw": db.Jsonb(row.raw),
            }
            for row in rows
        ],
        conflict_columns=("broker", "uic", "asset_type"),
    )


def security_ids(broker: str) -> dict[SecurityKey, int]:
    return {
        SecurityKey(broker=broker, uic=row["uic"], asset_type=row["asset_type"]): int(row["id"])
        for row in db.select(sql.SELECT_SECURITY_IDS, {"broker": broker})
    }


def upsert_ledger(connection_id: int, portfolio_id: int, rows: list[LedgerRow], ids: dict[SecurityKey, int]) -> int:
    return db.upsert_many(
        "ledger_transactions",
        [
            {
                "connection_id": connection_id,
                "portfolio_id": portfolio_id,
                "account_key": row.account_key,
                "broker_ref": row.broker_ref,
                "kind": row.kind,
                "trade_date": row.trade_date,
                "value_date": row.value_date,
                "security_id": ids[row.security] if row.security else None,
                "quantity": row.quantity,
                "price": row.price,
                "currency": row.currency,
                "amount_local": row.amount_local,
                "account_currency": row.account_currency,
                "amount_account": row.amount_account,
                "base_currency": row.base_currency,
                "amount_base": row.amount_base,
                "fx_rate_base": row.fx_rate_base,
                "related_ref": row.related_ref,
                "description": row.description,
                "source_endpoint": row.source_endpoint,
                "raw": db.Jsonb(row.raw),
            }
            for row in rows
        ],
        conflict_columns=("connection_id", "broker_ref"),
    )


def delete_superseded_fills(connection_id: int) -> int:
    """Drop provisional fill rows once the booked trade for the same order is in the ledger."""
    return db.execute(sql.DELETE_SUPERSEDED_FILLS, {"connection_id": connection_id})


def upsert_position_snapshots(
    connection_id: int, portfolio_id: int, rows: list[PositionSnapshotRow], ids: dict[SecurityKey, int]
) -> int:
    return db.upsert_many(
        "position_snapshots",
        [
            {
                "connection_id": connection_id,
                "portfolio_id": portfolio_id,
                "snapshot_date": row.snapshot_date,
                "account_key": row.account_key,
                "broker_position_id": row.broker_position_id,
                "security_id": ids[row.security],
                "quantity": row.quantity,
                "open_price": row.open_price,
                "current_price": row.current_price,
                "currency": row.currency,
                "market_value_local": row.market_value_local,
                "market_value_base": row.market_value_base,
                "fx_rate_base": row.fx_rate_base,
                "raw": db.Jsonb(row.raw),
                "fetched_at": row.fetched_at,
            }
            for row in rows
        ],
        conflict_columns=("connection_id", "snapshot_date", "broker_position_id"),
    )


def upsert_cash_snapshots(connection_id: int, portfolio_id: int, rows: list[CashSnapshotRow]) -> int:
    return db.upsert_many(
        "cash_snapshots",
        [
            {
                "connection_id": connection_id,
                "portfolio_id": portfolio_id,
                "snapshot_date": row.snapshot_date,
                "account_key": row.account_key,
                "currency": row.currency,
                "cash_balance": row.cash_balance,
                "total_value": row.total_value,
                "raw": db.Jsonb(row.raw),
                "fetched_at": row.fetched_at,
            }
            for row in rows
        ],
        conflict_columns=("connection_id", "snapshot_date", "account_key", "currency"),
    )


def upsert_orders(connection_id: int, portfolio_id: int, rows: list[OrderRecord], ids: dict[SecurityKey, int]) -> int:
    return db.upsert_many(
        "orders",
        [
            {
                "connection_id": connection_id,
                "portfolio_id": portfolio_id,
                "broker_order_id": row.broker_order_id,
                "account_key": row.account_key,
                "security_id": ids.get(row.security) if row.security else None,
                "instrument_symbol": row.instrument_symbol,
                "instrument_name": row.instrument_name,
                "status": row.status,
                "broker_status": row.broker_status,
                "is_open": row.is_open,
                "buy_sell": row.buy_sell,
                "order_type": row.order_type,
                "duration": row.duration,
                "quantity": row.quantity,
                "filled_quantity": row.filled_quantity,
                "price": row.price,
                "average_fill_price": row.average_fill_price,
                "currency": row.currency,
                "placed_at": row.placed_at,
                "last_activity_at": row.last_activity_at,
                "expires_at": row.expires_at,
                "order_relation": row.order_relation,
                "source_endpoint": row.source_endpoint,
                "raw": db.Jsonb(row.raw),
                "fetched_at": row.fetched_at,
                "updated_at": datetime.now(UTC),
            }
            for row in rows
        ],
        conflict_columns=("connection_id", "broker_order_id"),
    )


def ledger_quantities(connection_id: int, as_of: date) -> dict[int, Decimal]:
    return {
        int(row["security_id"]): Decimal(row["quantity"])
        for row in db.select(sql.SELECT_LEDGER_QUANTITIES, {"connection_id": connection_id, "as_of": as_of})
        if row["security_id"] is not None
    }


def ledger_cash(connection_id: int, as_of: date) -> dict[tuple[str | None, str | None], Decimal]:
    return {
        (row["account_key"], row["currency"]): Decimal(row["balance"])
        for row in db.select(sql.SELECT_LEDGER_CASH, {"connection_id": connection_id, "as_of": as_of})
    }


def latest_position_snapshot(connection_id: int) -> list[dict[str, Any]]:
    return db.select(sql.SELECT_LATEST_POSITION_SNAPSHOT, {"connection_id": connection_id})


def latest_cash_snapshot(connection_id: int) -> list[dict[str, Any]]:
    return db.select(sql.SELECT_LATEST_CASH_SNAPSHOT, {"connection_id": connection_id})


def ledger_summary(connection_id: int) -> list[dict[str, Any]]:
    return db.select(sql.SELECT_LEDGER_SUMMARY, {"connection_id": connection_id})
