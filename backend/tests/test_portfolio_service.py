from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services import portfolio_service


def test_summarize_counts_open_positions_and_reads_broker_cash() -> None:
    portfolios = [
        {
            "id": 1,
            "name": "Pension",
            "broker_name": "Saxo Long Name",
            "display_name": "Pension",
            "base_currency": "DKK",
            "broker": "saxo",
            "environment": "live",
        },
        {"id": 2, "name": "IBKR", "base_currency": "DKK", "broker": None, "environment": None},
    ]
    aum = [
        {
            "portfolio_id": 1,
            "snapshot_date": date(2026, 9, 18),
            "cash_balance": Decimal("100"),
            "total_value": Decimal("410"),
            "unbooked": Decimal("3"),
        }
    ]
    cash = [
        {"portfolio_id": 1, "currency": "DKK", "cash_balance": Decimal("60")},
        {"portfolio_id": 1, "currency": "USD", "cash_balance": Decimal("6")},
    ]
    positions = [
        {"portfolio_id": 1, "status": "open", "value_base": Decimal("200")},
        {"portfolio_id": 1, "status": "open", "value_base": Decimal("105")},
        {"portfolio_id": 1, "status": "closed", "value_base": Decimal("0")},
    ]
    accounts = [{"portfolio_id": 1, "id": 11, "account_id": "123/2", "currency": "USD", "active": True}]
    saxo, ibkr = portfolio_service.summarize(portfolios, aum, cash, positions, accounts)
    assert saxo["accounts"] == [
        {"id": 11, "account_id": "123/2", "currency": "USD", "label": "123/2 (USD)", "active": True}
    ]
    assert ibkr["accounts"] == []
    assert saxo["name"] == "Pension" and saxo["broker_name"] == "Saxo Long Name" and saxo["display_name"] == "Pension"
    assert ibkr["name"] == "IBKR" and ibkr["broker_name"] == "IBKR" and ibkr["display_name"] is None
    assert saxo["open_positions"] == 2 and saxo["positions_value_base"] == Decimal("305")
    assert saxo["cash_base"] == Decimal("100") and saxo["total_value_base"] == Decimal("410")
    assert saxo["unbooked_base"] == Decimal("3") and saxo["unexplained_base"] == Decimal("2")
    assert [row["currency"] for row in saxo["cash_by_currency"]] == ["DKK", "USD"]
    assert ibkr["open_positions"] == 0 and ibkr["positions_value_base"] == Decimal("0")
    assert ibkr["cash_base"] is None and ibkr["unexplained_base"] is None and ibkr["cash_by_currency"] == []
    assert ibkr["unbooked_base"] is None


def test_normalize_display_name_trims_and_blanks_to_none() -> None:
    assert portfolio_service.normalize_display_name("  Saxo   pension ") == "Saxo pension"
    assert portfolio_service.normalize_display_name("   ") is None
    assert portfolio_service.normalize_display_name(None) is None
