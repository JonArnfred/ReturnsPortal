"""Domain records written by broker mappings. Broker-neutral; all money is Decimal."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

LedgerKind = Literal[
    "trade",
    "corporate_action",
    "deposit",
    "withdrawal",
    "transfer",
    "dividend",
    "withholding_tax",
    "commission",
    "fee",
    "tax",
    "interest",
    "lending_income",
    "other",
]


class SecurityKey(BaseModel, frozen=True):
    """Broker-side identity of a listing."""

    broker: str
    uic: int
    asset_type: str


class SecurityRecord(BaseModel):
    key: SecurityKey
    symbol: str
    ticker: str
    mic: str | None
    name: str | None
    currency: str | None
    exchange_id: str | None
    isin: str | None = None
    raw: dict[str, Any]


class ExchangeRecord(BaseModel):
    exchange_id: str
    mic: str | None
    iso_mic: str | None
    operating_mic: str | None
    name: str | None
    country_code: str | None
    currency: str | None
    timezone: str | None
    raw: dict[str, Any]


class LedgerRow(BaseModel):
    """One ledger transaction. Signs follow the ledger convention: cash in and quantity bought are positive."""

    broker_ref: str
    kind: LedgerKind
    trade_date: date
    value_date: date | None
    account_key: str | None
    security: SecurityKey | None
    quantity: Decimal | None
    price: Decimal | None
    currency: str
    amount_local: Decimal
    account_currency: str | None
    amount_account: Decimal | None
    base_currency: str
    amount_base: Decimal | None
    fx_rate_base: Decimal | None
    related_ref: str | None
    description: str | None
    source_endpoint: str
    raw: dict[str, Any]


class PositionSnapshotRow(BaseModel):
    snapshot_date: date
    account_key: str | None
    broker_position_id: str
    security: SecurityKey
    quantity: Decimal
    open_price: Decimal | None
    current_price: Decimal | None
    currency: str | None
    market_value_local: Decimal | None
    market_value_base: Decimal | None
    fx_rate_base: Decimal | None
    raw: dict[str, Any]
    fetched_at: datetime


class BrokerFxRate(BaseModel):
    """A broker's own FX rate for one currency on one day: ``rate`` in the reporting currency per unit
    (used to split NAV differences), ``quote_rate`` as the broker states it, in ``quote_currency``."""

    day: date
    currency: str
    rate: Decimal
    quote_currency: str
    quote_rate: Decimal


class CashSnapshotRow(BaseModel):
    snapshot_date: date
    account_key: str
    currency: str
    cash_balance: Decimal
    total_value: Decimal | None
    raw: dict[str, Any]
    fetched_at: datetime


OrderStatus = Literal["working", "filled", "cancelled", "expired", "rejected", "other"]


class OrderRecord(BaseModel):
    """One broker order in its latest known state. Working and historical orders share this shape."""

    broker_order_id: str
    account_key: str | None
    security: SecurityKey | None
    instrument_symbol: str | None
    instrument_name: str | None
    status: OrderStatus
    broker_status: str | None
    is_open: bool
    buy_sell: Literal["buy", "sell"] | None
    order_type: str | None
    duration: str | None
    quantity: Decimal | None
    filled_quantity: Decimal | None
    price: Decimal | None
    average_fill_price: Decimal | None
    currency: str | None
    placed_at: datetime | None
    last_activity_at: datetime | None
    expires_at: datetime | None
    order_relation: str | None
    source_endpoint: str
    raw: dict[str, Any]
    fetched_at: datetime


PriceSource = Literal["saxo", "yahoo", "ibkr"]


class DailyBar(BaseModel):
    """One trading day of a security, split-adjusted, in the instrument currency (never GBX/ZAc)."""

    security_id: int
    price_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: Decimal | None
    currency: str | None
    source: PriceSource
