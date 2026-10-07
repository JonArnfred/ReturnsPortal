"""Daily FX from ECB reference rates, crossed through EUR into each portfolio's base currency.

Rates are stored as base currency per one unit of the foreign currency and only for the days ECB
publishes; the PnL engine carries the last rate forward over weekends and holidays. The first run
loads the full history since 1999, later runs the 90-day feed (ECB occasionally revises recent
days), and a run whose stored data is older than the 90-day window falls back to the full feed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app import db
from app.connectors.ecb import mapping
from app.connectors.ecb.client import EcbClient
from app.domain.models import BrokerFxRate
from app.services import fx_sql as sql
from app.services import settings_service

logger = logging.getLogger("returns-portal.fx")

RECENT_WINDOW = timedelta(days=80)


@dataclass
class FxSyncReport:
    feed: str = ""
    ecb_rows: int = 0
    fx_rows: int = 0
    base_currencies: list[str] = field(default_factory=list)
    first_date: date | None = None
    last_date: date | None = None
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "feed": self.feed,
            "ecb_rows": self.ecb_rows,
            "fx_rows": self.fx_rows,
            "base_currencies": self.base_currencies,
            "first_date": self.first_date.isoformat() if self.first_date else None,
            "last_date": self.last_date.isoformat() if self.last_date else None,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


def needs_full_history(last_stored: date | None, today: date) -> bool:
    return last_stored is None or last_stored < today - RECENT_WINDOW


def base_currencies() -> list[str]:
    """The reporting currency (also before any portfolio exists) and every portfolio's currency."""
    rows = db.select(sql.SELECT_BASE_CURRENCIES)
    return sorted({str(row["base_currency"]) for row in rows} | {settings_service.reporting_currency()})


def crossed_base_currencies() -> list[str]:
    """Base currencies that already have crossed rates stored."""
    return sorted(str(row["base_currency"]) for row in db.select(sql.SELECT_CROSSED_BASE_CURRENCIES))


def split_bases(bases: list[str], crossed: list[str]) -> tuple[list[str], list[str]]:
    """(bases to bring up to date, bases to build from the whole stored history). A base that appears
    for the first time, such as when a broker with another base currency is connected, needs every
    stored ECB day crossed, not just the days of the feed that was fetched."""
    return [base for base in bases if base in crossed], [base for base in bases if base not in crossed]


def store_ecb_rates(rates: list[mapping.EcbRate]) -> int:
    return db.upsert_many(
        "ecb_reference_rates",
        [
            {
                "rate_date": rate.rate_date,
                "currency": rate.currency,
                "units_per_eur": rate.units_per_eur,
                "fetched_at": datetime.now(UTC),
            }
            for rate in rates
        ],
        conflict_columns=("rate_date", "currency"),
    )


def rebuild_fx_rates(since: date | None = None, bases: list[str] | None = None) -> int:
    """Recompute the crossed table from the stored ECB rates for every base currency in use."""
    rows = db.select(sql.SELECT_ECB_RATES_SINCE, {"since": since})
    ecb = [mapping.EcbRate.model_validate(row) for row in rows]
    written = 0
    for base in bases or base_currencies():
        crossed = mapping.cross_to_base(ecb, base)
        # One transaction, so a concurrent ingest never finds the base's rates deleted and not yet rewritten.
        with db.transaction() as conn:
            db.execute(sql.DELETE_FX_RATES_SINCE, {"base_currency": base, "since": since}, conn=conn)
            written += db.upsert_many(
                "fx_rates",
                [rate.model_dump() for rate in crossed],
                conflict_columns=("base_currency", "currency", "rate_date"),
                conn=conn,
            )
    return written


def sync_fx(client: EcbClient | None = None, today: date | None = None) -> FxSyncReport:
    """Fetch what is missing from ECB and rebuild the crossed rates. Safe to rerun."""
    report = FxSyncReport()
    today = today or datetime.now(UTC).date()
    coverage = db.select_one(sql.SELECT_ECB_COVERAGE) or {}
    full = needs_full_history(coverage.get("last_date"), today)
    owned = client is None
    client = client or EcbClient()
    try:
        feed = client.fetch(full_history=full)
        report.feed = feed.url
        if feed.status_code != 200:
            report.error = f"ECB answered HTTP {feed.status_code}"
            return report
        rates = mapping.parse_feed(feed.text)
        if not rates:
            report.error = "ECB feed contained no rates"
            return report
        report.ecb_rows = store_ecb_rates(rates)
        report.first_date = min(rate.rate_date for rate in rates)
        report.last_date = max(rate.rate_date for rate in rates)
        report.base_currencies = base_currencies()
        current, new = split_bases(report.base_currencies, crossed_base_currencies())
        report.fx_rows = rebuild_fx_rates(since=None if full else report.first_date, bases=current) if current else 0
        if new:
            report.fx_rows += rebuild_fx_rates(since=None, bases=new)
    finally:
        if owned:
            client.close()
        report.finished_at = datetime.now(UTC)
    return report


def fx_status() -> list[dict[str, Any]]:
    return db.select(sql.SELECT_FX_STATUS)


def fx_series(
    base_currency: str, currency: str, date_gte: date | None = None, date_lte: date | None = None
) -> list[dict[str, Any]]:
    return db.select(
        sql.SELECT_FX_SERIES,
        {"base_currency": base_currency, "currency": currency, "date_gte": date_gte, "date_lte": date_lte},
    )


def rate_on(base_currency: str, currency: str, day: date) -> Decimal | None:
    """Base currency per one unit of ``currency`` on ``day``, forward-filled; 1 for the base itself."""
    if currency == base_currency:
        return Decimal(1)
    params = {"base_currency": base_currency, "currency": currency, "day": day}
    row = db.select_one(sql.SELECT_FX_RATE_ON_OR_BEFORE, params)
    return None if row is None else Decimal(row["rate"])


def upsert_broker_rates(portfolio_id: int, rates: list[BrokerFxRate]) -> int:
    """The broker's own FX rates (reporting currency per unit), used to split NAV differences."""
    return db.upsert_many(
        "broker_fx_rates",
        [
            {
                "portfolio_id": portfolio_id,
                "rate_date": rate.day,
                "currency": rate.currency,
                "rate": rate.rate,
                "quote_currency": rate.quote_currency,
                "quote_rate": rate.quote_rate,
                "fetched_at": datetime.now(UTC),
            }
            for rate in rates
        ],
        conflict_columns=("portfolio_id", "rate_date", "currency"),
    )
