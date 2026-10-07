"""Application settings changed from the UI. The reporting currency is the one that matters: every
portfolio is booked and reported in it, so changing it means re-mapping each broker's ledger and
rebuilding the PnL (``app.tasks.apply_reporting_currency``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app import db
from app.config import settings
from app.services import settings_sql as sql

REPORTING_CURRENCY = "reporting_currency"


def reporting_currency() -> str:
    """The stored choice, else ``REPORTING_CURRENCY`` from the environment."""
    row = db.select_one(sql.SELECT_SETTING, {"key": REPORTING_CURRENCY})
    return str(row["value"]) if row else settings.reporting_currency


@dataclass(frozen=True)
class CurrencyOption:
    code: str
    allowed: bool
    reason: str | None = None


def currency_options() -> list[CurrencyOption]:
    """Every currency the ECB fixes (and EUR), with why a currency cannot be chosen, if it cannot."""
    codes = {str(row["currency"]) for row in db.select(sql.SELECT_ECB_CURRENCIES)} | {"EUR", reporting_currency()}
    saxo = {str(row["base_currency"]) for row in db.select(sql.SELECT_SAXO_CLIENT_CURRENCIES)}
    options = []
    for code in sorted(codes):
        reason = None
        if saxo and code not in saxo:
            reason = f"Saxo books in {', '.join(sorted(saxo))}; the reporting currency must match"
        options.append(CurrencyOption(code, reason is None, reason))
    return options


def portfolio_currencies() -> list[dict[str, Any]]:
    return db.select(sql.SELECT_PORTFOLIO_CURRENCIES)


def recalculation_pending(currency: str, portfolios: list[dict[str, Any]]) -> bool:
    """True while a portfolio is still booked or built in another currency than ``currency``."""
    return any(
        row["booked_currency"] != currency or (row["built_currency"] not in (None, currency)) for row in portfolios
    )


def set_reporting_currency(currency: str) -> None:
    """Store the reporting currency. Raises ValueError for a currency that cannot be chosen."""
    code = currency.strip().upper()
    option = next((option for option in currency_options() if option.code == code), None)
    if option is None:
        raise ValueError(f"{code or currency!r} is not a currency the ECB publishes reference rates for")
    if not option.allowed:
        raise ValueError(option.reason or f"{code} cannot be chosen")
    db.execute(sql.UPSERT_SETTING, {"key": REPORTING_CURRENCY, "value": code})
