"""Mapping tests use rows shaped like real Saxo payloads captured on 2026-09-18 (values altered)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.connectors.saxo import mapping
from app.connectors.saxo.dto import (
    SaxoBalance,
    SaxoBooking,
    SaxoExchange,
    SaxoInstrumentDetails,
    SaxoOrderActivity,
    SaxoPosition,
    SaxoTrade,
)

TRADE: dict[str, Any] = {
    "Uic": 1000001,
    "Price": 394.0,
    "Amount": 1.0,
    "TradeId": "5000000001",
    "OrderId": "6000000001",
    "AccountId": "ACC1",
    "AssetType": "Stock",
    "TradeDate": "2021-02-26",
    "TradeType": "Limit",
    "ValueDate": "2021-03-02",
    "TradedValue": -394.0,
    "ToOpenOrClose": "ToOpen",
    "ClientCurrency": "DKK",
    "TradeEventType": "Bought",
    "AccountCurrency": "DKK",
    "InstrumentSymbol": "ACME:xnas",
    "TradeExecutionTime": "2021-02-26T17:56:52.270000Z",
    "InstrumentDescription": "Acme Corp.",
    "BookedAmountClientCurrency": -2457.0,
    "BookedAmountAccountCurrency": -2457.0,
    "Venue": "Exchange",
    "Strike": 0.0,
    "UnknownField": {"ignored": True},
}

SHARE_BOOKING: dict[str, Any] = {
    "Uic": 1000001,
    "Date": "2021-02-26",
    "Amount": -394.0,
    "Currency": "USD",
    "AccountId": "ACC1",
    "AssetType": "Stock",
    "ValueDate": "2021-03-02",
    "BkAmountId": "7000000001",
    "BkAmountType": "Share Amount",
    "ClientCurrency": "DKK",
    "ConversionRate": 6.2360406,
    "RelatedTradeId": "5000000001",
    "AccountCurrency": "DKK",
    "InstrumentSymbol": "ACME:xnas",
    "AmountClientCurrency": -2457.0,
    "AmountAccountCurrency": -2457.0,
    "InstrumentDescription": "Acme Corp.",
}


def booking(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Uic": 1000003,
        "Date": "2021-03-11",
        "Amount": 2.8,
        "Currency": "USD",
        "AccountId": "ACC2",
        "AssetType": "Stock",
        "ValueDate": "2021-03-11",
        "BkAmountId": "7000000002",
        "BkAmountType": "Corporate Actions - Cash Dividends",
        "ClientCurrency": "DKK",
        "ConversionRate": 6.17546,
        "RelatedTradeId": "0",
        "AccountCurrency": "USD",
        "InstrumentSymbol": "BETA:xnas",
        "AmountClientCurrency": 17.310834,
        "AmountAccountCurrency": 2.8,
        "InstrumentDescription": "Beta Corp.",
    }
    row.update(overrides)
    return row


def test_split_symbol() -> None:
    assert mapping.split_symbol("ACME:xnas") == ("ACME", "XNAS")
    assert mapping.split_symbol("NOVO-B:xcse") == ("NOVO-B", "XCSE")
    assert mapping.split_symbol("CASHINTR") == ("CASHINTR", None)
    assert mapping.split_symbol(None) == ("", None)


def test_decimals_come_from_shortest_float_repr() -> None:
    trade = SaxoTrade.model_validate({**TRADE, "Price": 1769.1054, "TradedValue": -1769.11})
    assert trade.price == Decimal("1769.1054") and trade.traded_value == Decimal("-1769.11")
    assert trade.trade_date == date(2021, 2, 26) and trade.trade_execution_time is not None


def test_trade_with_share_booking_uses_booked_cash_leg() -> None:
    trade = SaxoTrade.model_validate(TRADE)
    share = SaxoBooking.model_validate(SHARE_BOOKING)
    row = mapping.map_trade(
        trade, TRADE, base_currency="DKK", instrument_currency="USD", share_booking=share, account_key="AK1"
    )
    assert row.kind == "trade" and row.broker_ref == "trade:5000000001" and row.related_ref == "booking:7000000001"
    assert row.security is not None and (row.security.uic, row.security.asset_type) == (1000001, "Stock")
    assert row.quantity == Decimal("1") and row.price == Decimal("394")
    assert row.currency == "USD" and row.amount_local == Decimal("-394")
    assert row.account_currency == "DKK" and row.amount_account == Decimal("-2457")
    assert row.amount_base == Decimal("-2457") and row.fx_rate_base is not None
    assert row.fx_rate_base.quantize(Decimal("0.0001")) == Decimal("6.2360")
    assert row.account_key == "AK1" and row.value_date == date(2021, 3, 2)


def test_trade_without_booking_falls_back_to_traded_value() -> None:
    trade = SaxoTrade.model_validate({**TRADE, "TradeEventType": "Sold", "Amount": -1.0, "TradedValue": 394.0})
    row = mapping.map_trade(
        trade, TRADE, base_currency="DKK", instrument_currency="USD", share_booking=None, account_key=None
    )
    assert row.kind == "trade" and row.quantity == Decimal("-1") and row.amount_local == Decimal("394")
    assert row.currency == "USD" and row.amount_base == Decimal("-2457")  # from the row's booked amounts


def test_corporate_action_pseudo_trade_has_no_cash() -> None:
    pseudo = {**TRADE, "TradeType": "NotAvailable", "BookedAmountClientCurrency": 0.0, "Amount": 10.0, "Price": 39.4}
    row = mapping.map_trade(
        SaxoTrade.model_validate(pseudo),
        pseudo,
        base_currency="DKK",
        instrument_currency="USD",
        share_booking=None,
        account_key=None,
    )
    assert row.kind == "corporate_action" and row.quantity == Decimal("10")
    assert row.amount_local == 0 and row.amount_base == 0 and row.fx_rate_base is None


def test_booking_kinds() -> None:
    cases = {
        "Commission": "commission",
        "Corporate Actions - Cash Dividends": "dividend",
        "Corporate Actions - Withholding Tax": "withholding_tax",
        "Exchange Fee": "fee",
        "Exchange Subscription Fee": "fee",
        "Depository Charges": "fee",
        "Corporate Actions - Fee": "fee",
        "Italian Financial Transaction Tax": "tax",
        "Withholding Tax ASK Account": "tax",
        "Interest": "interest",
        "Securities Lending Client Fee": "lending_income",
        "Something New": "other",
    }
    for bk_type, expected in cases.items():
        assert mapping.booking_kind(SaxoBooking.model_validate(booking(BkAmountType=bk_type))) == expected, bk_type
    assert mapping.booking_kind(SaxoBooking.model_validate(booking(BkAmountType="Share Amount"))) is None


def test_cash_amount_is_deposit_withdrawal_or_transfer() -> None:
    deposit = booking(
        BkAmountType="Cash Amount",
        InstrumentSymbol="CASHDEPWI",
        Amount=10000.0,
        Currency="DKK",
        AssetType="Cash",
        Uic=9465,
    )
    withdrawal = booking(
        BkAmountType="Cash Amount",
        InstrumentSymbol="CASHOUT",
        Amount=-500.0,
        Currency="DKK",
        AssetType="Cash",
        Uic=9465,
    )
    transfer = booking(
        BkAmountType="Cash Amount",
        InstrumentSymbol="CASHINTR",
        Amount=-1000.0,
        Currency="DKK",
        AssetType="Cash",
        Uic=9465,
    )
    kinds = [mapping.booking_kind(SaxoBooking.model_validate(row)) for row in (deposit, withdrawal, transfer)]
    assert kinds == ["deposit", "withdrawal", "transfer"]
    row = mapping.map_booking(SaxoBooking.model_validate(deposit), deposit, base_currency="DKK", account_key="AK1")
    assert row is not None and row.security is None and row.kind == "deposit" and row.amount_local == Decimal("10000")


def test_dividend_booking_maps_with_fx_and_security() -> None:
    raw = booking()
    row = mapping.map_booking(SaxoBooking.model_validate(raw), raw, base_currency="DKK", account_key="AK2")
    assert row is not None
    assert row.kind == "dividend" and row.broker_ref == "booking:7000000002" and row.related_ref is None
    assert row.security is not None and row.security.uic == 1000003
    assert row.currency == "USD" and row.amount_local == Decimal("2.8")
    assert row.account_currency == "USD" and row.amount_account == Decimal("2.8")
    assert row.amount_base == Decimal("17.310834")
    assert row.fx_rate_base is not None and row.fx_rate_base.quantize(Decimal("0.0001")) == Decimal("6.1824")
    assert row.trade_date == date(2021, 3, 11) and row.description == "Beta Corp."


def test_share_booking_is_folded_into_trade() -> None:
    assert (
        mapping.map_booking(
            SaxoBooking.model_validate(SHARE_BOOKING), SHARE_BOOKING, base_currency="DKK", account_key=None
        )
        is None
    )


def test_position_and_balance_mapping() -> None:
    raw = {
        "PositionId": "9100000001",
        "NetPositionId": "1000002__Share",
        "PositionBase": {
            "Uic": 1000002,
            "Amount": 3.0,
            "Status": "Open",
            "AccountKey": "AK1",
            "AssetType": "Stock",
            "OpenPrice": 1500.0,
        },
        "PositionView": {
            "CurrentPrice": 1607.94,
            "MarketValue": 4823.82,
            "MarketValueInBaseCurrency": 31457.31,
            "ConversionRateCurrent": 6.521245,
            "ExposureCurrency": "USD",
        },
        "DisplayAndFormat": {"Symbol": "WIDG:xnys", "Currency": "USD", "Description": "Widget Systems Inc."},
        "Exchange": {"ExchangeId": "NYSE", "Description": "New York Stock Exchange"},
    }
    fetched = datetime(2026, 9, 18, 17, 50, tzinfo=UTC)
    row = mapping.map_position(SaxoPosition.model_validate(raw), raw, snapshot_date=fetched.date(), fetched_at=fetched)
    assert row.broker_position_id == "9100000001" and row.security.uic == 1000002 and row.account_key == "AK1"
    assert row.quantity == Decimal("3") and row.current_price == Decimal("1607.94") and row.currency == "USD"
    assert row.market_value_base == Decimal("31457.31") and row.fx_rate_base == Decimal("6.521245")
    security = mapping.security_from_position(SaxoPosition.model_validate(raw), raw)
    assert (security.ticker, security.mic, security.currency, security.exchange_id) == ("WIDG", "XNYS", "USD", "NYSE")

    balance = {"Currency": "USD", "CashBalance": -1200.5, "TotalValue": 52000.0, "OrdersCount": 2}
    cash = mapping.map_balance(
        SaxoBalance.model_validate(balance),
        balance,
        account_key="AK3",
        snapshot_date=fetched.date(),
        fetched_at=fetched,
    )
    assert cash.currency == "USD" and cash.cash_balance == Decimal("-1200.5") and cash.total_value == Decimal("52000.0")


def test_instrument_and_exchange_mapping() -> None:
    details = {
        "Uic": 207,
        "AssetType": "Stock",
        "Symbol": "AMZN:xnas",
        "Description": "Amazon.com Inc.",
        "CurrencyCode": "USD",
        "Exchange": {"CountryCode": "US", "ExchangeId": "NASDAQ", "Name": "NASDAQ"},
        "PrimaryListing": 207,
    }
    security = mapping.map_instrument(SaxoInstrumentDetails.model_validate(details), details)
    assert (security.key.uic, security.key.asset_type, security.ticker, security.mic) == (207, "Stock", "AMZN", "XNAS")
    assert security.currency == "USD" and security.exchange_id == "NASDAQ" and security.name == "Amazon.com Inc."

    exchange = {
        "ExchangeId": "AMEX",
        "Mic": "XASE",
        "IsoMic": "XASE",
        "OperatingMic": "XNYS",
        "Name": "NYSE American",
        "CountryCode": "US",
        "Currency": "USD",
        "TimeZone": "America/New_York",
        "ExchangeSessions": [],
    }
    record = mapping.map_exchange(SaxoExchange.model_validate(exchange), exchange)
    assert (record.exchange_id, record.mic, record.operating_mic, record.timezone) == (
        "AMEX",
        "XASE",
        "XNYS",
        "America/New_York",
    )


FILL = {
    "Uic": 133675,
    "LogId": "9000000001",
    "Price": 4800.0,
    "Amount": 1.0,
    "Status": "FinalFill",
    "BuySell": "Sell",
    "OrderId": "9000000002",
    "AccountId": "123456INET",
    "AssetType": "Stock",
    "OrderType": "Limit",
    "SubStatus": "Confirmed",
    "FillAmount": 1.0,
    "PositionId": "9000000003",
    "ActivityTime": "2026-09-21T07:05:10.367000Z",
    "AveragePrice": 4940.0,
    "FilledAmount": 1.0,
    "ExecutionPrice": 4940.0,
}


def test_executed_fill_becomes_a_provisional_trade_at_the_ecb_rate() -> None:
    activity = SaxoOrderActivity.model_validate(FILL)
    row = mapping.map_fill(
        activity,
        FILL,
        base_currency="DKK",
        instrument_currency="USD",
        account_key="AK1",
        account_currency="USD",
        fx_rate_base=Decimal("6.4"),
        description="Samsung GDR",
    )
    assert row is not None
    assert row.kind == "trade" and row.broker_ref == "fill:9000000001" and row.related_ref == "order:9000000002"
    assert row.trade_date == date(2026, 9, 21) and row.value_date is None
    assert row.quantity == Decimal("-1") and row.price == Decimal("4940")
    assert row.currency == "USD" and row.amount_local == Decimal("4940") and row.amount_account == Decimal("4940")
    assert row.amount_base == Decimal("31616.0") and row.fx_rate_base == Decimal("6.4")
    assert row.source_endpoint == mapping.EXECUTED_ENDPOINT and row.description == "Samsung GDR"


def test_only_fill_events_with_a_price_become_trades() -> None:
    kwargs: dict[str, Any] = dict(
        base_currency="DKK",
        instrument_currency="USD",
        account_key=None,
        account_currency="DKK",
        fx_rate_base=None,
        description=None,
    )
    working = SaxoOrderActivity.model_validate(
        {**FILL, "Status": "Working", "FillAmount": None, "ExecutionPrice": None}
    )
    assert mapping.map_fill(working, FILL, **kwargs) is None
    partial = mapping.map_fill(
        SaxoOrderActivity.model_validate({**FILL, "Status": "Fill", "BuySell": "Buy"}), FILL, **kwargs
    )
    assert partial is not None and partial.quantity == Decimal("1") and partial.amount_local == Decimal("-4940")
    assert partial.amount_base is None and partial.amount_account is None  # no rate: base and account legs stay empty
