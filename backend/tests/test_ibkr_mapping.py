"""Flex rows recorded from a live statement (2026-09-21), reduced to the fields that matter."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.connectors.ibkr import mapping
from app.connectors.ibkr.dto import (
    FlexCashReportCurrency,
    FlexCashTransaction,
    FlexConversionRate,
    FlexCorporateAction,
    FlexEquitySummary,
    FlexOpenPosition,
    FlexPriorPeriodPosition,
    FlexSecurityInfo,
    FlexTrade,
    FlexTransfer,
    parse_statements,
)

D = Decimal
BASE = "EUR"


def no_fx(currency: str, day: date) -> Decimal | None:
    return None


def usd_fx(currency: str, day: date) -> Decimal | None:
    return D("0.85") if currency == "USD" else None


# The user reports in EUR too, so IBKR's own fxRateToBase is taken as is.
NATIVE = mapping.BaseConversion(base_currency=BASE, broker_base=BASE, fx=no_fx)
NATIVE_USD = mapping.BaseConversion(base_currency=BASE, broker_base=BASE, fx=usd_fx)


def dkk_fx(currency: str, day: date) -> Decimal | None:
    return {"EUR": D("7.46"), "ILS": D("2.1")}.get(currency)


# The user reports in DKK: every base amount comes from the ECB rate, never from fxRateToBase.
REPORTED_IN_DKK = mapping.BaseConversion(base_currency="DKK", broker_base="EUR", fx=dkk_fx)


STOCK_BUY = {
    "tradeID": "8000000001",
    "accountId": "U1",
    "currency": "ILS",
    "fxRateToBase": "0.28492",
    "assetCategory": "STK",
    "symbol": "ORBT",
    "description": "ORBIT INDUSTRIES LTD",
    "conid": "100000011",
    "isin": "IL0000000011",
    "listingExchange": "TASE",
    "multiplier": "1",
    "tradeDate": "2026-08-20",
    "dateTime": "2026-08-20;05:55:26",
    "settleDateTarget": "2026-08-21",
    "quantity": "49",
    "tradePrice": "18.6",
    "tradeMoney": "911.4",
    "proceeds": "-911.4",
    "taxes": "0",
    "ibCommission": "-15",
    "ibCommissionCurrency": "ILS",
    "netCash": "-926.4",
    "buySell": "BUY",
    "openCloseIndicator": "O",
    "notes": "P",
    "levelOfDetail": "EXECUTION",
    "ibOrderID": "8000000003",
}

FX_SELL = {
    "tradeID": "8000000002",
    "accountId": "U1",
    "currency": "ILS",
    "fxRateToBase": "0.28492",
    "assetCategory": "CASH",
    "symbol": "EUR.ILS",
    "description": "EUR.ILS",
    "conid": "44495104",
    "tradeDate": "2026-08-20",
    "dateTime": "2026-08-20;05:53:08",
    "settleDateTarget": "2026-08-24",
    "quantity": "-1000",
    "tradePrice": "3.4896",
    "tradeMoney": "-3489.6",
    "proceeds": "3489.6",
    "ibCommission": "-1.7127",
    "ibCommissionCurrency": "EUR",
    "buySell": "SELL",
    "levelOfDetail": "EXECUTION",
}


def test_stock_trade_is_a_trade_row_plus_a_linked_commission() -> None:
    rows = mapping.map_trade(FlexTrade.model_validate(STOCK_BUY), STOCK_BUY, conversion=NATIVE)
    assert [row.kind for row in rows] == ["trade", "commission"]
    trade, commission = rows
    assert trade.broker_ref == "trade:8000000001"
    assert trade.security == mapping.security_key(100000011, "STK")
    assert (trade.quantity, trade.price, trade.currency) == (D("49"), D("18.6"), "ILS")
    assert (trade.amount_local, trade.account_currency, trade.amount_account) == (D("-911.4"), "ILS", D("-911.4"))
    assert trade.amount_base == D("-911.4") * D("0.28492") and trade.fx_rate_base == D("0.28492")
    assert (trade.trade_date, trade.value_date) == (date(2026, 8, 20), date(2026, 8, 21))
    assert trade.raw["executed_at"] == "2026-08-20T05:55:26"
    assert commission.broker_ref == "commission:8000000001" and commission.related_ref == "trade:8000000001"
    assert commission.security == trade.security
    assert (commission.currency, commission.amount_local, commission.amount_base) == (
        "ILS",
        D("-15"),
        D("-15") * D("0.28492"),
    )
    assert trade.amount_local + commission.amount_local == D("-926.4")  # netCash


def test_currency_conversion_becomes_two_transfer_legs_and_a_base_commission() -> None:
    rows = mapping.map_trade(FlexTrade.model_validate(FX_SELL), FX_SELL, conversion=NATIVE)
    assert [(row.kind, row.currency) for row in rows] == [
        ("transfer", "EUR"),
        ("transfer", "ILS"),
        ("commission", "EUR"),
    ]
    eur, ils, commission = rows
    assert eur.broker_ref == "fx:8000000002:EUR" and eur.related_ref == "fx:8000000002:ILS"
    assert (eur.amount_local, eur.amount_base, eur.fx_rate_base) == (D("-1000"), D("-1000"), D(1))
    assert (ils.amount_local, ils.fx_rate_base) == (D("3489.6"), D("0.28492"))
    assert ils.amount_base == D("3489.6") * D("0.28492")
    assert eur.security is None and ils.security is None and commission.security is None
    assert (commission.amount_local, commission.amount_base) == (D("-1.7127"), D("-1.7127"))


def test_cancelled_executions_and_zero_quantities_give_nothing() -> None:
    cancelled = {**STOCK_BUY, "notes": "Ca;P"}
    assert mapping.map_trade(FlexTrade.model_validate(cancelled), cancelled, conversion=NATIVE) == []
    zero = {**STOCK_BUY, "quantity": "0"}
    assert mapping.map_trade(FlexTrade.model_validate(zero), zero, conversion=NATIVE) == []


def test_commission_in_a_third_currency_uses_the_fx_lookup() -> None:
    row = {**STOCK_BUY, "ibCommission": "-2", "ibCommissionCurrency": "USD"}
    _, commission = mapping.map_trade(FlexTrade.model_validate(row), row, conversion=NATIVE_USD)
    assert (commission.currency, commission.fx_rate_base, commission.amount_base) == ("USD", D("0.85"), D("-1.70"))
    _, unknown = mapping.map_trade(FlexTrade.model_validate(row), row, conversion=NATIVE)
    assert unknown.amount_base is None and unknown.fx_rate_base is None


@pytest.mark.parametrize(
    ("type_", "amount", "kind"),
    [
        ("Dividends", "1090.04", "dividend"),
        ("Payment In Lieu Of Dividends", "3", "dividend"),
        ("Withholding Tax", "-218.01", "withholding_tax"),
        ("Broker Interest Paid", "-1.83", "interest"),
        ("Broker Interest Received", "1.32", "interest"),
        ("Other Fees", "-0.01", "fee"),
        ("Commission Adjustments", "0.5", "commission"),
        ("Deposits/Withdrawals", "5000", "deposit"),
        ("Deposits/Withdrawals", "-500", "withdrawal"),
        ("Deposits & Withdrawals", "5000", "deposit"),
        ("Something New", "1", "other"),
    ],
)
def test_cash_transaction_kinds(type_: str, amount: str, kind: str) -> None:
    row = {
        "transactionID": "1",
        "accountId": "U1",
        "currency": "ILS",
        "fxRateToBase": "0.28426",
        "dateTime": "2026-09-08;20:20:00",
        "settleDate": "2026-09-08",
        "amount": amount,
        "type": type_,
        "reportDate": "2026-09-11",
        "levelOfDetail": "DETAIL",
    }
    mapped = mapping.map_cash_transaction(FlexCashTransaction.model_validate(row), row, conversion=NATIVE)
    assert mapped is not None
    assert mapped.kind == kind and mapped.broker_ref == "cash:1"
    assert (mapped.trade_date, mapped.value_date) == (date(2026, 9, 11), date(2026, 9, 8))  # booked on reportDate
    assert (mapped.amount_local, D(amount) * D("0.28426")) == (D(amount), mapped.amount_base)
    assert mapped.security is None


def test_dividend_and_withholding_carry_the_security_and_the_action_link() -> None:
    row = {
        "transactionID": "8000000004",
        "accountId": "U1",
        "currency": "ILS",
        "fxRateToBase": "0.28426",
        "assetCategory": "STK",
        "symbol": "ORBT",
        "description": "ORBT(IL0000000011) CASH DIVIDEND ILS 2.5 PER SHARE (Ordinary Dividend)",
        "conid": "100000011",
        "isin": "IL0000000011",
        "listingExchange": "TASE",
        "dateTime": "2026-09-08;20:20:00",
        "settleDate": "2026-09-08",
        "amount": "875.00",
        "type": "Dividends",
        "exDate": "2026-08-28",
        "actionID": "8000000005",
        "levelOfDetail": "DETAIL",
    }
    mapped = mapping.map_cash_transaction(FlexCashTransaction.model_validate(row), row, conversion=NATIVE)
    assert mapped is not None
    assert mapped.security == mapping.security_key(100000011, "STK")
    assert mapped.related_ref == "action:8000000005" and mapped.kind == "dividend"


def test_corporate_action_and_position_transfer() -> None:
    action = {
        "accountId": "U1",
        "currency": "USD",
        "fxRateToBase": "0.85",
        "assetCategory": "STK",
        "symbol": "ABC",
        "conid": "42",
        "reportDate": "2026-05-02",
        "dateTime": "2026-05-01;20:25:00",
        "actionDescription": "ABC SPLIT 2 FOR 1",
        "quantity": "100",
        "proceeds": "0",
        "type": "FS",
        "actionID": "99",
        "transactionID": "777",
    }
    mapped = mapping.map_corporate_action(FlexCorporateAction.model_validate(action), action, conversion=NATIVE)
    assert mapped is not None
    assert (mapped.kind, mapped.broker_ref, mapped.quantity, mapped.amount_local) == (
        "corporate_action",
        "corp:777",
        D(100),
        D(0),
    )
    assert mapped.trade_date == date(2026, 5, 1) and mapped.security == mapping.security_key(42, "STK")

    transfer = {
        "accountId": "U1",
        "currency": "USD",
        "assetCategory": "STK",
        "symbol": "ABC",
        "conid": "42",
        "date": "2026-06-01",
        "type": "ACATS",
        "direction": "IN",
        "quantity": "10",
        "transferPrice": "12.5",
        "positionAmount": "125",
        "transactionID": "888",
    }
    mapped_transfer = mapping.map_transfer(FlexTransfer.model_validate(transfer), transfer, conversion=NATIVE_USD)
    assert mapped_transfer is not None
    assert (mapped_transfer.kind, mapped_transfer.quantity, mapped_transfer.amount_local) == ("transfer", D(10), D(0))
    assert mapped_transfer.security == mapping.security_key(42, "STK")


def test_open_position_cash_report_and_nav_snapshots() -> None:
    fetched = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    position = {
        "accountId": "U1",
        "currency": "ILS",
        "fxRateToBase": "0.28",
        "assetCategory": "STK",
        "symbol": "ORBT",
        "conid": "100000011",
        "reportDate": "2026-09-18",
        "position": "350",
        "markPrice": "19.57",
        "positionValue": "6849.5",
        "openPrice": "18.9",
        "fifoPnlUnrealized": "234.5",
        "side": "Long",
        "levelOfDetail": "SUMMARY",
    }
    snapshot = mapping.map_open_position(
        FlexOpenPosition.model_validate(position),
        position,
        snapshot_date=date(2026, 9, 18),
        fetched_at=fetched,
        conversion=NATIVE,
    )
    assert snapshot.broker_position_id == "U1:100000011" and snapshot.account_key == "U1"
    assert (snapshot.quantity, snapshot.current_price, snapshot.market_value_local) == (D(350), D("19.57"), D("6849.5"))
    assert snapshot.market_value_base == D("6849.5") * D("0.28") and snapshot.open_price == D("18.9")

    cash = {
        "accountId": "U1",
        "currency": "ILS",
        "levelOfDetail": "Currency",
        "toDate": "2026-09-18",
        "endingCash": "12.5",
    }
    cash_row = mapping.map_cash_report(
        FlexCashReportCurrency.model_validate(cash), cash, snapshot_date=date(2026, 9, 18), fetched_at=fetched
    )
    assert cash_row is not None
    assert (cash_row.account_key, cash_row.currency, cash_row.cash_balance, cash_row.total_value) == (
        "U1",
        "ILS",
        D("12.5"),
        None,
    )
    summary = {**cash, "currency": "BASE_SUMMARY"}
    assert (
        mapping.map_cash_report(
            FlexCashReportCurrency.model_validate(summary), summary, snapshot_date=date(2026, 9, 18), fetched_at=fetched
        )
        is None
    )

    nav = {
        "accountId": "U1",
        "currency": "EUR",
        "reportDate": "2026-08-19",
        "cash": "4000.00",
        "stock": "6000.00",
        "dividendAccruals": "245.00",
        "interestAccruals": "5.00",
        "total": "10250.00",
    }
    nav_row = mapping.map_nav(
        FlexEquitySummary.model_validate(nav),
        nav,
        snapshot_date=date(2026, 9, 18),
        fetched_at=fetched,
        conversion=NATIVE,
    )
    assert nav_row is not None
    assert (nav_row.account_key, nav_row.currency, nav_row.snapshot_date) == ("", "EUR", date(2026, 8, 19))
    assert nav_row.total_value == D("10000.00")  # accruals are not in the ledger until paid


def test_prior_period_positions_and_open_positions_give_daily_marks() -> None:
    row = {
        "accountId": "U1",
        "currency": "EUR",
        "assetCategory": "STK",
        "symbol": "ETP5",
        "conid": "100000052",
        "date": "20261005",
        "price": "2.7958",
        "priorMtmPnl": "12.5",
    }
    mark = mapping.map_prior_period_position(FlexPriorPeriodPosition.model_validate(row))
    assert mark == mapping.PriceMark(mapping.security_key(100000052, "STK"), date(2026, 10, 5), D("2.7958"), "EUR")
    for blank in ({"price": ""}, {"date": ""}, {"assetCategory": "CASH"}):
        assert mapping.map_prior_period_position(FlexPriorPeriodPosition.model_validate({**row, **blank})) is None

    trade = {
        "currency": "EUR",
        "assetCategory": "STK",
        "conid": "100000052",
        "tradeDate": "20251212",
        "quantity": "635",
        "tradePrice": "1.6",
        "closePrice": "1.569",
        "tradeID": "1",
    }
    trade_mark = mapping.trade_mark(FlexTrade.model_validate(trade))
    assert trade_mark is not None and (trade_mark.day, trade_mark.price) == (date(2025, 12, 12), D("1.569"))
    assert mapping.trade_mark(FlexTrade.model_validate({**trade, "notes": "Ca"})) is None
    assert mapping.trade_mark(FlexTrade.model_validate({**trade, "assetCategory": "CASH"})) is None

    position = {"assetCategory": "STK", "conid": "1", "currency": "ILS", "position": "5", "markPrice": "13.97"}
    open_mark = mapping.open_position_mark(FlexOpenPosition.model_validate(position), snapshot_date=date(2026, 10, 6))
    assert open_mark is not None and (open_mark.day, open_mark.price) == (date(2026, 10, 6), D("13.97"))


def test_conversion_rates_cross_into_the_reporting_currency() -> None:
    def ecb(currency: str, day: date) -> Decimal | None:
        return D("7.46") if currency == "EUR" else None

    dkk = mapping.BaseConversion(base_currency="DKK", broker_base="EUR", fx=ecb)
    rows = [
        FlexConversionRate.model_validate(
            {"reportDate": "2026-07-29", "fromCurrency": cur, "toCurrency": "EUR", "rate": rate}
        )
        for cur, rate in (("ILS", "0.2915"), ("DKK", "0.13405"), ("USD", "0.86"))
    ]
    mapped = mapping.map_conversion_rates(rows, conversion=dkk, currencies={"EUR", "ILS", "DKK"})
    rates = {(rate.day, rate.currency): rate.rate for rate in mapped}
    quotes = {rate.currency: (rate.quote_rate, rate.quote_currency) for rate in mapped}
    assert quotes == {"EUR": (D(1), "EUR"), "ILS": (D("0.2915"), "EUR"), "DKK": (D("0.13405"), "EUR")}
    day = date(2026, 7, 29)
    assert rates == {
        (day, "EUR"): D("7.46"),  # the account base, at the rate the broker NAV is converted with
        (day, "ILS"): D("0.2915") * D("7.46"),
        (day, "DKK"): D("0.13405") * D("7.46"),  # IBKR's DKK/EUR crossed back: not exactly 1
    }


def test_reporting_in_another_currency_converts_with_ecb_rates() -> None:
    trade, commission = mapping.map_trade(FlexTrade.model_validate(STOCK_BUY), STOCK_BUY, conversion=REPORTED_IN_DKK)
    assert (trade.base_currency, trade.fx_rate_base, trade.amount_base) == ("DKK", D("2.1"), D("-911.4") * D("2.1"))
    assert commission.amount_base == D("-15") * D("2.1")
    eur, ils, fee = mapping.map_trade(FlexTrade.model_validate(FX_SELL), FX_SELL, conversion=REPORTED_IN_DKK)
    assert (eur.fx_rate_base, eur.amount_base) == (D("7.46"), D("-7460"))
    assert (ils.fx_rate_base, fee.fx_rate_base) == (D("2.1"), D("7.46"))

    fetched = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)
    position = {
        "accountId": "U1",
        "currency": "ILS",
        "fxRateToBase": "0.28",
        "assetCategory": "STK",
        "conid": "1",
        "reportDate": "2026-09-18",
        "position": "10",
        "markPrice": "20",
        "positionValue": "200",
    }
    snapshot = mapping.map_open_position(
        FlexOpenPosition.model_validate(position),
        position,
        snapshot_date=date(2026, 9, 18),
        fetched_at=fetched,
        conversion=REPORTED_IN_DKK,
    )
    assert (snapshot.fx_rate_base, snapshot.market_value_base) == (D("2.1"), D("420"))

    nav = {
        "accountId": "U1",
        "currency": "EUR",
        "reportDate": "2026-08-19",
        "cash": "100",
        "total": "1000",
        "interestAccruals": "1",
    }
    nav_row = mapping.map_nav(
        FlexEquitySummary.model_validate(nav),
        nav,
        snapshot_date=date(2026, 9, 18),
        fetched_at=fetched,
        conversion=REPORTED_IN_DKK,
    )
    assert nav_row is not None
    assert (nav_row.currency, nav_row.cash_balance, nav_row.total_value) == ("DKK", D("746"), D("999") * D("7.46"))
    unknown = mapping.BaseConversion(base_currency="DKK", broker_base="EUR", fx=no_fx)
    assert (
        mapping.map_nav(
            FlexEquitySummary.model_validate(nav),
            nav,
            snapshot_date=date(2026, 9, 18),
            fetched_at=fetched,
            conversion=unknown,
        )
        is None
    )


def test_security_mapping_and_exchange_mics() -> None:
    info = {
        "symbol": "ETP5",
        "description": "EXAMPLE 5X LONG INDEX ETP",
        "conid": "100000052",
        "currency": "EUR",
        "assetCategory": "STK",
        "subCategory": "ETF",
        "isin": "XS0000000052",
        "listingExchange": "IBIS2",
        "multiplier": "1",
    }
    record = mapping.map_security(FlexSecurityInfo.model_validate(info), info)
    assert record.key == mapping.security_key(100000052, "STK")
    assert (record.ticker, record.mic, record.currency, record.isin) == ("ETP5", "XETR", "EUR", "XS0000000052")
    assert mapping.mic_for("TASE") == "XTAE" and mapping.mic_for("IDEALFX") is None and mapping.mic_for(None) is None


def test_account_information_is_stripped_of_personal_data() -> None:
    row = {"accountId": "U1", "currency": "EUR", "name": "Tester", "street": "Somewhere 1", "dateOfBirth": "1980-01-01"}
    assert mapping.strip_account_information(row) == {"accountId": "U1", "currency": "EUR", "name": "Tester"}


def test_parse_statements_reads_sections_and_account_information() -> None:
    xml = """<FlexQueryResponse queryName="q" type="AF"><FlexStatements count="1">
    <FlexStatement accountId="U1" fromDate="2026-08-20" toDate="2026-09-18" period="LastNCalendarDays"
                   whenGenerated="2026-09-21;06:26:55">
      <AccountInformation accountId="U1" currency="EUR" name="Tester" accountType="Individual" dateOpened="2025-10-01"/>
      <Trades><Trade tradeID="1" quantity="2"/></Trades>
      <CorporateActions/>
    </FlexStatement></FlexStatements></FlexQueryResponse>"""
    (statement,) = parse_statements(xml)
    assert (statement.account_id, statement.from_date, statement.to_date) == (
        "U1",
        date(2026, 8, 20),
        date(2026, 9, 18),
    )
    assert statement.sections["AccountInformation"][0]["dateOpened"] == "2025-10-01"
    assert (
        statement.sections["Trades"] == [{"tradeID": "1", "quantity": "2"}]
        and statement.sections["CorporateActions"] == []
    )
    with pytest.raises(ValueError):
        parse_statements("<FlexStatementResponse><Status>Fail</Status></FlexStatementResponse>")
