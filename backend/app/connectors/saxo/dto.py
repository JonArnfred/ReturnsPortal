"""Pydantic views of Saxo OpenAPI payloads. Field names mirror Saxo; only fields we read are declared.

Unknown fields are ignored. Numbers arrive as JSON floats and are converted through their shortest
string form, so ``1769.11`` becomes ``Decimal("1769.11")`` rather than a binary approximation.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _to_decimal(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    return value


def _to_date(value: Any) -> Any:
    if isinstance(value, str) and len(value) >= 10:
        return date.fromisoformat(value[:10])
    return value


Money = Annotated[Decimal, BeforeValidator(_to_decimal)]
OptionalMoney = Annotated[Decimal | None, BeforeValidator(_to_decimal)]
SaxoDate = Annotated[date, BeforeValidator(_to_date)]
OptionalSaxoDate = Annotated[date | None, BeforeValidator(_to_date)]


class SaxoModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, frozen=True)


class SaxoClientInfo(SaxoModel):
    client_key: str = Field(alias="ClientKey")
    client_id: str | None = Field(default=None, alias="ClientId")
    name: str | None = Field(default=None, alias="Name")
    default_currency: str | None = Field(default=None, alias="DefaultCurrency")


class SaxoAccount(SaxoModel):
    account_key: str = Field(alias="AccountKey")
    account_id: str | None = Field(default=None, alias="AccountId")
    currency: str | None = Field(default=None, alias="Currency")
    account_type: str | None = Field(default=None, alias="AccountType")
    active: bool = Field(default=True, alias="Active")


class SaxoTrade(SaxoModel):
    """Row of the Client Services trades report."""

    trade_id: str = Field(alias="TradeId")
    order_id: str | None = Field(default=None, alias="OrderId")
    account_id: str | None = Field(default=None, alias="AccountId")
    uic: int = Field(alias="Uic")
    asset_type: str = Field(alias="AssetType")
    instrument_symbol: str | None = Field(default=None, alias="InstrumentSymbol")
    instrument_description: str | None = Field(default=None, alias="InstrumentDescription")
    trade_event_type: str = Field(alias="TradeEventType")
    trade_type: str | None = Field(default=None, alias="TradeType")
    to_open_or_close: str | None = Field(default=None, alias="ToOpenOrClose")
    trade_date: SaxoDate = Field(alias="TradeDate")
    value_date: OptionalSaxoDate = Field(default=None, alias="ValueDate")
    trade_execution_time: datetime | None = Field(default=None, alias="TradeExecutionTime")
    amount: Money = Field(alias="Amount", description="Signed quantity: bought positive, sold negative.")
    price: Money = Field(alias="Price")
    traded_value: Money = Field(alias="TradedValue", description="Cash effect in instrument currency, buy negative.")
    account_currency: str | None = Field(default=None, alias="AccountCurrency")
    client_currency: str | None = Field(default=None, alias="ClientCurrency")
    booked_amount_account_currency: OptionalMoney = Field(default=None, alias="BookedAmountAccountCurrency")
    booked_amount_client_currency: OptionalMoney = Field(default=None, alias="BookedAmountClientCurrency")


class SaxoBooking(SaxoModel):
    """Row of the Client Services bookings report: every cash movement on an account."""

    bk_amount_id: str = Field(alias="BkAmountId")
    bk_amount_type: str = Field(alias="BkAmountType")
    bk_amount_type_id: str | None = Field(default=None, alias="BkAmountTypeId")
    account_id: str | None = Field(default=None, alias="AccountId")
    date: SaxoDate = Field(alias="Date")
    value_date: OptionalSaxoDate = Field(default=None, alias="ValueDate")
    uic: int | None = Field(default=None, alias="Uic")
    asset_type: str | None = Field(default=None, alias="AssetType")
    instrument_symbol: str | None = Field(default=None, alias="InstrumentSymbol")
    instrument_description: str | None = Field(default=None, alias="InstrumentDescription")
    amount: Money = Field(alias="Amount")
    currency: str = Field(alias="Currency")
    amount_account_currency: OptionalMoney = Field(default=None, alias="AmountAccountCurrency")
    account_currency: str | None = Field(default=None, alias="AccountCurrency")
    amount_client_currency: OptionalMoney = Field(default=None, alias="AmountClientCurrency")
    client_currency: str | None = Field(default=None, alias="ClientCurrency")
    conversion_rate: OptionalMoney = Field(default=None, alias="ConversionRate")
    related_trade_id: str | None = Field(default=None, alias="RelatedTradeId")
    related_position_id: str | None = Field(default=None, alias="RelatedPositionId")
    amount_class: str | None = Field(default=None, alias="AmountClass")
    cost_class: str | None = Field(default=None, alias="CostClass")
    ca_event_name: str | None = Field(default=None, alias="CaEventName")


class SaxoPositionBase(SaxoModel):
    uic: int = Field(alias="Uic")
    asset_type: str = Field(alias="AssetType")
    amount: Money = Field(alias="Amount")
    open_price: OptionalMoney = Field(default=None, alias="OpenPrice")
    account_key: str | None = Field(default=None, alias="AccountKey")
    account_id: str | None = Field(default=None, alias="AccountId")
    status: str | None = Field(default=None, alias="Status")
    execution_time_open: datetime | None = Field(default=None, alias="ExecutionTimeOpen")


class SaxoPositionView(SaxoModel):
    current_price: OptionalMoney = Field(default=None, alias="CurrentPrice")
    market_value: OptionalMoney = Field(default=None, alias="MarketValue")
    market_value_in_base_currency: OptionalMoney = Field(default=None, alias="MarketValueInBaseCurrency")
    conversion_rate_current: OptionalMoney = Field(default=None, alias="ConversionRateCurrent")
    exposure_currency: str | None = Field(default=None, alias="ExposureCurrency")


class SaxoDisplayAndFormat(SaxoModel):
    symbol: str | None = Field(default=None, alias="Symbol")
    currency: str | None = Field(default=None, alias="Currency")
    description: str | None = Field(default=None, alias="Description")


class SaxoExchangeInfo(SaxoModel):
    exchange_id: str | None = Field(default=None, alias="ExchangeId")
    description: str | None = Field(default=None, alias="Description")


class SaxoPosition(SaxoModel):
    position_id: str = Field(alias="PositionId")
    net_position_id: str | None = Field(default=None, alias="NetPositionId")
    base: SaxoPositionBase = Field(alias="PositionBase")
    view: SaxoPositionView | None = Field(default=None, alias="PositionView")
    display: SaxoDisplayAndFormat | None = Field(default=None, alias="DisplayAndFormat")
    exchange: SaxoExchangeInfo | None = Field(default=None, alias="Exchange")


class SaxoOrderDuration(SaxoModel):
    duration_type: str | None = Field(default=None, alias="DurationType")
    expiration_date_time: datetime | None = Field(default=None, alias="ExpirationDateTime")


class SaxoOrder(SaxoModel):
    """A working order from ``port/v1/orders/me``."""

    order_id: str = Field(alias="OrderId")
    account_key: str | None = Field(default=None, alias="AccountKey")
    account_id: str | None = Field(default=None, alias="AccountId")
    uic: int | None = Field(default=None, alias="Uic")
    asset_type: str | None = Field(default=None, alias="AssetType")
    buy_sell: str | None = Field(default=None, alias="BuySell")
    amount: OptionalMoney = Field(default=None, alias="Amount")
    filled_amount: OptionalMoney = Field(default=None, alias="FilledAmount")
    price: OptionalMoney = Field(default=None, alias="Price")
    open_order_type: str | None = Field(default=None, alias="OpenOrderType", description="Limit, Market, Stop...")
    order_type: str | None = Field(default=None, alias="OrderType")
    duration: SaxoOrderDuration | None = Field(default=None, alias="Duration")
    status: str | None = Field(default=None, alias="Status")
    order_time: datetime | None = Field(default=None, alias="OrderTime")
    order_relation: str | None = Field(default=None, alias="OrderRelation")
    display: SaxoDisplayAndFormat | None = Field(default=None, alias="DisplayAndFormat")
    exchange: SaxoExchangeInfo | None = Field(default=None, alias="Exchange")


class SaxoOrderActivity(SaxoModel):
    """One event from ``cs/v1/audit/orderactivities`` (shapes confirmed against live data, 2026-09-19).

    ``Status`` is one of Placed, Working, Changed, DoneForDay, Fill (partial), FinalFill, Cancelled,
    Expired; ``SubStatus`` is Requested, Confirmed or Rejected. Fill events carry the cumulative
    ``FilledAmount``, this event's ``FillAmount`` and the ``AveragePrice``. Rows name the account by
    ``AccountId`` only. Every field but the id is optional so an unexpected payload degrades to a
    sparse row instead of failing the ingest.
    """

    order_id: str = Field(alias="OrderId")
    log_id: str | None = Field(default=None, alias="LogId", description="Unique id of the audit event.")
    position_id: str | None = Field(default=None, alias="PositionId", description="Position a fill opened.")
    activity_time: datetime | None = Field(default=None, alias="ActivityTime")
    account_id: str | None = Field(default=None, alias="AccountId")
    uic: int | None = Field(default=None, alias="Uic")
    asset_type: str | None = Field(default=None, alias="AssetType")
    buy_sell: str | None = Field(default=None, alias="BuySell")
    amount: OptionalMoney = Field(default=None, alias="Amount")
    filled_amount: OptionalMoney = Field(default=None, alias="FilledAmount", description="Cumulative.")
    fill_amount: OptionalMoney = Field(default=None, alias="FillAmount", description="This event only.")
    price: OptionalMoney = Field(default=None, alias="Price")
    average_price: OptionalMoney = Field(default=None, alias="AveragePrice")
    execution_price: OptionalMoney = Field(default=None, alias="ExecutionPrice")
    order_type: str | None = Field(default=None, alias="OrderType")
    duration: SaxoOrderDuration | None = Field(default=None, alias="Duration")
    status: str | None = Field(default=None, alias="Status")
    sub_status: str | None = Field(default=None, alias="SubStatus")
    order_relation: str | None = Field(default=None, alias="OrderRelation")


class SaxoBalance(SaxoModel):
    currency: str = Field(alias="Currency")
    cash_balance: Money = Field(alias="CashBalance")
    total_value: OptionalMoney = Field(default=None, alias="TotalValue")


class SaxoInstrumentExchange(SaxoModel):
    exchange_id: str | None = Field(default=None, alias="ExchangeId")
    name: str | None = Field(default=None, alias="Name")
    country_code: str | None = Field(default=None, alias="CountryCode")


class SaxoInstrumentDetails(SaxoModel):
    uic: int = Field(alias="Uic")
    asset_type: str = Field(alias="AssetType")
    symbol: str = Field(alias="Symbol")
    description: str | None = Field(default=None, alias="Description")
    currency_code: str | None = Field(default=None, alias="CurrencyCode")
    exchange: SaxoInstrumentExchange | None = Field(default=None, alias="Exchange")
    primary_listing: int | None = Field(default=None, alias="PrimaryListing")


class SaxoExchange(SaxoModel):
    exchange_id: str = Field(alias="ExchangeId")
    mic: str | None = Field(default=None, alias="Mic")
    iso_mic: str | None = Field(default=None, alias="IsoMic")
    operating_mic: str | None = Field(default=None, alias="OperatingMic")
    name: str | None = Field(default=None, alias="Name")
    country_code: str | None = Field(default=None, alias="CountryCode")
    currency: str | None = Field(default=None, alias="Currency")
    time_zone: str | int | None = Field(default=None, alias="TimeZone", description="Saxo time zone id or name.")


class SaxoBar(SaxoModel):
    """One bar from ``chart/v3/charts`` (``Horizon=1440`` gives daily bars, split-adjusted)."""

    time: datetime = Field(alias="Time")
    open: OptionalMoney = Field(default=None, alias="Open")
    high: OptionalMoney = Field(default=None, alias="High")
    low: OptionalMoney = Field(default=None, alias="Low")
    close: OptionalMoney = Field(default=None, alias="Close")
    volume: OptionalMoney = Field(default=None, alias="Volume")
