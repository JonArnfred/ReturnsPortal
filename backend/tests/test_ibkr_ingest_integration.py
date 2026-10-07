"""IBKR ingest end to end against real PostgreSQL; needs TEST_DATABASE_URL.

A captured statement (rows shaped like real Flex rows) goes into ``broker_raw_payloads``;
the ingest must replay it into a ledger whose cash per currency and quantity per security match the
broker's own cash report and open positions, and must expose the NAV series the engine reads.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pandas
import pytest
from pytest import MonkeyPatch

from app import db
from app.config import settings
from app.connectors.ibkr import ingest as ibkr_ingest
from app.connectors.yahoo.client import YahooHistory
from app.services import price_service

D = Decimal
STATEMENT = {"accountId": "U1", "fromDate": "2026-08-20", "toDate": "2026-09-18", "period": "x", "whenGenerated": "x"}


@pytest.fixture
def ibkr_db(migrated_db: None, monkeypatch: MonkeyPatch) -> Iterator[None]:
    db.execute(
        "INSERT INTO broker_connections (broker, environment, access_token_encrypted,"
        " access_token_expires_at, client_key, client_name, base_currency, query_id,"
        " last_sync_started_at)"
        " VALUES ('ibkr', 'live', 'x', CURRENT_TIMESTAMP, 'U1', 'Tester', 'EUR', '1', CURRENT_TIMESTAMP)"
    )
    db.execute(
        "INSERT INTO broker_accounts (connection_id, account_key, account_id, currency, raw)"
        " VALUES (1, 'U1', 'U1', 'EUR', '{}')"
    )
    # The user reports in DKK; the broker's base is EUR, so every base amount is crossed by ECB.
    monkeypatch.setattr(settings, "reporting_currency", "DKK")
    db.execute(
        "INSERT INTO fx_rates (rate_date, base_currency, currency, rate, source) VALUES"
        " ('2026-08-01', 'DKK', 'EUR', 7.5, 'ecb'), ('2026-08-01', 'DKK', 'ILS', 2.0, 'ecb'),"
        " ('2026-08-01', 'DKK', 'DKK', 1, 'identity')"
    )
    yield


def capture(section: str, rows: list[dict[str, Any]]) -> None:
    db.execute(
        "INSERT INTO broker_raw_payloads (connection_id, endpoint, params, status_code, payload)"
        " VALUES (1, %s, '{}', 200, %s)",
        (f"flex/statement/{section}", db.Jsonb({"statement": STATEMENT, "rows": rows})),
    )


ORBT = {
    "currency": "ILS",
    "assetCategory": "STK",
    "symbol": "ORBT",
    "description": "ORBIT INDUSTRIES LTD",
    "conid": "100000011",
    "isin": "IL0000000011",
    "listingExchange": "TASE",
}


def test_statement_replays_to_the_broker_cash_and_positions(ibkr_db: None) -> None:
    capture("SecuritiesInfo", [{**ORBT, "subCategory": "COMMON", "multiplier": "1"}])
    capture(
        "Trades",
        [
            # Convert 1000 EUR to ILS, then buy 100 ORBT at 20 with 15 ILS commission.
            {
                "tradeID": "fx1",
                "accountId": "U1",
                "currency": "ILS",
                "fxRateToBase": "0.28",
                "assetCategory": "CASH",
                "symbol": "EUR.ILS",
                "conid": "44495104",
                "tradeDate": "2026-08-20",
                "dateTime": "2026-08-20;05:53:08",
                "settleDateTarget": "2026-08-24",
                "quantity": "-1000",
                "tradePrice": "3.5",
                "proceeds": "3500",
                "ibCommission": "-2",
                "ibCommissionCurrency": "EUR",
                "buySell": "SELL",
                "levelOfDetail": "EXECUTION",
            },
            {
                **ORBT,
                "tradeID": "t1",
                "accountId": "U1",
                "fxRateToBase": "0.28",
                "tradeDate": "2026-08-20",
                "dateTime": "2026-08-20;05:55:26",
                "settleDateTarget": "2026-08-21",
                "quantity": "100",
                "tradePrice": "20",
                "proceeds": "-2000",
                "ibCommission": "-15",
                "ibCommissionCurrency": "ILS",
                "netCash": "-2015",
                "buySell": "BUY",
                "openCloseIndicator": "O",
                "notes": "P",
                "levelOfDetail": "EXECUTION",
            },
            {
                **ORBT,
                "tradeID": "cancelled",
                "accountId": "U1",
                "tradeDate": "2026-08-21",
                "quantity": "5",
                "notes": "Ca",
            },
        ],
    )
    capture(
        "CashTransactions",
        [
            {
                "transactionID": "dep",
                "accountId": "U1",
                "currency": "EUR",
                "fxRateToBase": "1",
                "dateTime": "2026-08-19",
                "settleDate": "2026-08-19",
                "amount": "5000",
                "type": "Deposits/Withdrawals",
                "levelOfDetail": "DETAIL",
            },
            {
                **ORBT,
                "transactionID": "div",
                "accountId": "U1",
                "fxRateToBase": "0.28",
                "dateTime": "2026-09-08;20:20:00",
                "settleDate": "2026-09-08",
                "amount": "300",
                "type": "Dividends",
                "actionID": "a1",
                "levelOfDetail": "DETAIL",
            },
            {
                **ORBT,
                "transactionID": "wht",
                "accountId": "U1",
                "fxRateToBase": "0.28",
                "dateTime": "2026-09-08;20:20:00",
                "settleDate": "2026-09-08",
                "amount": "-75",
                "type": "Withholding Tax",
                "actionID": "a1",
                "levelOfDetail": "DETAIL",
            },
            {
                "transactionID": "fee",
                "accountId": "U1",
                "currency": "ILS",
                "fxRateToBase": "0.28",
                "dateTime": "2026-09-01",
                "settleDate": "2026-09-01",
                "amount": "-10",
                "type": "Other Fees",
                "description": "TASE CUSTODY FEE",
                "levelOfDetail": "DETAIL",
            },
            {
                "transactionID": "int",
                "accountId": "U1",
                "currency": "EUR",
                "fxRateToBase": "1",
                "dateTime": "2026-09-03",
                "settleDate": "2026-09-03",
                "amount": "1.5",
                "type": "Broker Interest Received",
                "levelOfDetail": "DETAIL",
            },
        ],
    )
    capture(
        "OpenPositions",
        [
            {
                **ORBT,
                "accountId": "U1",
                "fxRateToBase": "0.29",
                "reportDate": "2026-09-18",
                "position": "100",
                "markPrice": "22",
                "positionValue": "2200",
                "openPrice": "20",
                "side": "Long",
                "levelOfDetail": "SUMMARY",
            }
        ],
    )
    capture(
        "CashReport",
        [
            {
                "accountId": "U1",
                "currency": "BASE_SUMMARY",
                "levelOfDetail": "Currency",
                "toDate": "2026-09-18",
                "endingCash": "9",
            },
            {
                "accountId": "U1",
                "currency": "EUR",
                "levelOfDetail": "Currency",
                "toDate": "2026-09-18",
                "endingCash": "3999.5",
            },
            {
                "accountId": "U1",
                "currency": "ILS",
                "levelOfDetail": "Currency",
                "toDate": "2026-09-18",
                "endingCash": "1700",
            },
        ],
    )
    capture(
        "EquitySummaryInBase",
        [
            {
                "accountId": "U1",
                "currency": "EUR",
                "reportDate": "2026-09-17",
                "cash": "4490",
                "stock": "600",
                "total": "5090",
            },
            {
                "accountId": "U1",
                "currency": "EUR",
                "reportDate": "2026-09-18",
                "cash": "4492.5",
                "stock": "638",
                "dividendAccruals": "0",
                "interestAccruals": "0.5",
                "total": "5131",
            },
        ],
    )

    report = ibkr_ingest.ingest(1)

    assert report.securities == 1 and report.trades == 2 and report.cash_transactions == 5
    assert report.ledger_rows == 10  # 2 fx legs + fx commission + trade + commission + 5 cash rows
    assert report.positions == 1 and report.cash_rows == 2 and report.nav_days == 2
    assert report.warnings == []
    assert report.reconciliation["position_issues"] == [] and report.reconciliation["cash_issues"] == []
    assert report.reconciliation["positions_checked"] == 1 and report.reconciliation["cash_checked"] == 2

    kinds = {row["broker_ref"]: row for row in db.select("SELECT * FROM ledger_transactions ORDER BY id")}
    assert kinds["trade:t1"]["kind"] == "trade" and kinds["trade:t1"]["quantity"] == D(100)
    assert kinds["commission:t1"]["related_ref"] == "trade:t1" and kinds["commission:t1"]["security_id"] is not None
    assert kinds["fx:fx1:EUR"]["amount_account"] == D(-1000) and kinds["fx:fx1:EUR"]["amount_base"] == D(-7500)
    assert kinds["fx:fx1:ILS"]["amount_base"] == D(7000) and kinds["trade:t1"]["base_currency"] == "DKK"
    assert kinds["cash:div"]["kind"] == "dividend" and kinds["cash:wht"]["kind"] == "withholding_tax"
    assert "cancelled" not in " ".join(kinds)
    # Cash per currency replays to the broker's ending balances.
    cash = {
        row["account_currency"]: row["balance"]
        for row in db.select(
            "SELECT account_currency, SUM(amount_account) AS balance FROM ledger_transactions GROUP BY account_currency"
        )
    }
    assert cash == {"EUR": D("3999.5"), "ILS": D("1700")}
    portfolio = db.select_one("SELECT * FROM portfolios")
    assert portfolio is not None and portfolio["name"] == "IBKR Tester" and portfolio["base_currency"] == "DKK"
    nav = db.select(
        "SELECT snapshot_date, currency, total_value FROM cash_snapshots WHERE account_key = '' ORDER BY snapshot_date"
    )
    assert [(row["snapshot_date"], row["currency"], row["total_value"]) for row in nav] == [
        (date(2026, 9, 17), "DKK", D("5090") * D("7.5")),
        (date(2026, 9, 18), "DKK", D("5130.5") * D("7.5")),
    ]
    [mark] = db.select("SELECT market_value_base, fx_rate_base FROM position_snapshots")
    assert (mark["market_value_base"], mark["fx_rate_base"]) == (D("4400"), D("2"))
    [position] = db.select("SELECT quantity, closed FROM positions")
    assert position["quantity"] == D(100) and position["closed"] is None

    # Rerunning is idempotent.
    again = ibkr_ingest.ingest(1)
    assert again.ledger_rows == 10 and db.select_one("SELECT COUNT(*) AS n FROM ledger_transactions")["n"] == 10  # type: ignore[index]


class FakeYahoo:
    """Serves fixed closes in the shape of a yfinance history frame."""

    def __init__(self, closes: dict[str, float]) -> None:
        self.closes = closes

    def fetch_daily(self, symbol: str, since: date, until: date | None = None) -> YahooHistory:
        index = pandas.to_datetime(list(self.closes))
        return YahooHistory(symbol, "ILS", pandas.DataFrame({"Close": list(self.closes.values())}, index=index))


def test_ibkr_marks_become_closes_and_yahoo_keeps_off_them(ibkr_db: None) -> None:
    capture("SecuritiesInfo", [{**ORBT, "subCategory": "COMMON", "multiplier": "1"}])
    capture(
        "Trades",
        [
            {
                **ORBT,
                "tradeID": "t1",
                "accountId": "U1",
                "fxRateToBase": "0.28",
                "tradeDate": "2026-08-20",
                "dateTime": "2026-08-20;05:55:26",
                "quantity": "100",
                "tradePrice": "40",
                "closePrice": "41",  # before the split below: on the old basis, not stored
                "proceeds": "-4000",
                "ibCommission": "0",
                "ibCommissionCurrency": "ILS",
                "levelOfDetail": "EXECUTION",
            },
            {
                **ORBT,
                "tradeID": "t2",
                "accountId": "U1",
                "fxRateToBase": "0.28",
                "tradeDate": "2026-09-11",
                "dateTime": "2026-09-11;09:15:00",
                "quantity": "10",
                "tradePrice": "20",
                "closePrice": "20.5",  # the opening day's mark, which Prior Period Positions lacks
                "proceeds": "-200",
                "ibCommission": "0",
                "ibCommissionCurrency": "ILS",
                "levelOfDetail": "EXECUTION",
            },
        ],
    )
    # A 2-for-1 split booked on 2026-09-09 after the close: that day's mark is on the old basis and is not stored.
    capture(
        "CorporateActions",
        [
            {
                **ORBT,
                "accountId": "U1",
                "fxRateToBase": "0.28",
                "reportDate": "2026-09-10",
                "dateTime": "2026-09-09;20:25:00",
                "actionDescription": "ORBT SPLIT 2 FOR 1",
                "quantity": "100",
                "proceeds": "0",
                "type": "FS",
                "actionID": "s1",
                "transactionID": "split1",
            }
        ],
    )
    period = {**ORBT, "accountId": "U1"}
    capture(
        "PriorPeriodPositions",
        [
            {**period, "date": "2026-09-09", "price": "40"},
            {**period, "date": "2026-09-16", "price": "21.5"},
            {**period, "date": "2026-09-17", "price": "21.8"},
            {
                "accountId": "U1",
                "currency": "EUR",
                "assetCategory": "CASH",
                "conid": "1",
                "date": "2026-09-17",
                "price": "1",
            },
        ],
    )
    capture(
        "OpenPositions",
        [{**ORBT, "accountId": "U1", "reportDate": "2026-09-18", "position": "200", "markPrice": "22"}],
    )

    report = ibkr_ingest.ingest(1)

    assert report.price_marks == 4
    closes = "SELECT price_date, close, source FROM daily_prices ORDER BY price_date"
    assert [tuple(row.values()) for row in db.select(closes)] == [
        (date(2026, 9, 11), D("20.5"), "ibkr"),
        (date(2026, 9, 16), D("21.5"), "ibkr"),
        (date(2026, 9, 17), D("21.8"), "ibkr"),
        (date(2026, 9, 18), D("22"), "ibkr"),
    ]

    # A Yahoo refresh fills the days IBKR did not mark and leaves the marked ones alone.
    security = db.select_one(
        "SELECT id, ticker, mic, currency, yahoo_symbol FROM securities s LEFT JOIN"
        " security_price_sources p ON p.security_id = s.id"
    )
    assert security is not None
    yahoo = FakeYahoo({"2026-09-15": 21.0, "2026-09-16": 20.9, "2026-09-17": 21.1})
    count, _ = price_service._sync_from_yahoo(yahoo, security, date(2026, 9, 15), date(2026, 9, 18))  # type: ignore[arg-type]
    assert count == 1
    assert [tuple(row.values()) for row in db.select(closes)][1:3] == [
        (date(2026, 9, 15), D("21"), "yahoo"),
        (date(2026, 9, 16), D("21.5"), "ibkr"),
    ]

    # A mark replaces a Yahoo close stored earlier for its day.
    capture("PriorPeriodPositions", [{**period, "date": "2026-09-15", "price": "21.2"}])
    ibkr_ingest.ingest(1)
    assert db.select_one("SELECT close, source FROM daily_prices WHERE price_date = '2026-09-15'") == {
        "close": D("21.2"),
        "source": "ibkr",
    }


def test_changing_the_reporting_currency_rebooks_every_portfolio(ibkr_db: None, monkeypatch: MonkeyPatch) -> None:
    from app import tasks
    from app.services import fx_service, settings_service

    capture(
        "CashTransactions",
        [
            {
                "transactionID": "dep",
                "accountId": "U1",
                "currency": "EUR",
                "fxRateToBase": "1",
                "dateTime": "2026-08-19",
                "settleDate": "2026-08-19",
                "amount": "5000",
                "type": "Deposits/Withdrawals",
                "levelOfDetail": "DETAIL",
            }
        ],
    )
    capture(
        "EquitySummaryInBase",
        [{"accountId": "U1", "currency": "EUR", "reportDate": "2026-09-18", "cash": "5000", "total": "5000"}],
    )
    ibkr_ingest.ingest(1)
    assert db.select_one("SELECT amount_base, base_currency FROM ledger_transactions") == {
        "amount_base": D(37500),
        "base_currency": "DKK",
    }

    # ECB fixes per euro; with no portfolio in USD yet, USD must still be crossed (the first-run case).
    db.execute(
        "INSERT INTO ecb_reference_rates (rate_date, currency, units_per_eur)"
        " VALUES ('2026-08-01', 'DKK', 7.5), ('2026-08-01', 'ILS', 3.75), ('2026-08-01', 'USD', 1.25)"
    )
    db.execute(
        "INSERT INTO broker_connections (broker, environment, access_token_encrypted, access_token_expires_at,"
        " base_currency) VALUES ('saxo', 'live', 'x', CURRENT_TIMESTAMP, 'DKK')"
    )
    options = {option.code: option for option in settings_service.currency_options()}
    assert not options["USD"].allowed and "Saxo books in DKK" in (options["USD"].reason or "")
    with pytest.raises(ValueError, match="Saxo"):
        settings_service.set_reporting_currency("USD")
    db.execute("DELETE FROM broker_connections WHERE broker = 'saxo'")
    with pytest.raises(ValueError, match="ECB"):
        settings_service.set_reporting_currency("XYZ")

    settings_service.set_reporting_currency("usd")
    assert settings_service.reporting_currency() == "USD"
    assert "USD" in fx_service.base_currencies()
    assert settings_service.recalculation_pending("USD", settings_service.portfolio_currencies())

    monkeypatch.setattr(fx_service, "sync_fx", lambda: fx_service.FxSyncReport())  # no network in tests
    report = tasks.apply_reporting_currency()

    assert report["currency"] == "USD" and all("error" not in row for row in report["ingest"])
    assert db.select_one("SELECT amount_base, base_currency FROM ledger_transactions") == {
        "amount_base": D(6250),  # 5000 EUR at 1.25 USD per EUR, crossed from the ECB fixings
        "base_currency": "USD",
    }
    assert db.select_one("SELECT base_currency FROM portfolios") == {"base_currency": "USD"}
    assert not settings_service.recalculation_pending("USD", settings_service.portfolio_currencies())
    nav = db.select_one("SELECT total_value FROM cash_snapshots WHERE account_key = '' AND currency = 'USD'")
    assert nav == {"total_value": D(6250)}
