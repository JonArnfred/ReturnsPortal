"""Daily prices: Saxo first, Yahoo for instruments Saxo no longer knows (and for every other broker's
securities), with a status row per security. IBKR's own daily marks are written by the IBKR ingest
(``upsert_broker_marks``) and are never overwritten by Yahoo.

Both sources deliver split-adjusted closes in the instrument currency; minor-unit quotes (GBX) are
normalised on the way in. Every fetch re-covers the last week so late corrections are picked up.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import app.services.connection_service as connections
from app import db
from app.config import settings
from app.connectors.saxo import mapping
from app.connectors.saxo import prices as saxo_prices
from app.connectors.saxo.client import FetchResult, SaxoClient
from app.connectors.saxo.dto import SaxoBar
from app.connectors.saxo.sync import client_for
from app.connectors.yahoo import mapping as yahoo_mapping
from app.connectors.yahoo.client import YahooClient
from app.domain.models import DailyBar
from app.services import price_sql as sql

logger = logging.getLogger("returns-portal.prices")

REFRESH_OVERLAP = timedelta(days=7)


@dataclass
class PriceSyncReport:
    connection_id: int
    securities: int = 0
    saxo: int = 0
    yahoo: int = 0
    unavailable: int = 0
    bars: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            **{key: value for key, value in self.__dict__.items() if not key.endswith("_at")},
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


def fetch_since(last_price_date: date | None, first_needed: date | None, today: date, history_start: date) -> date:
    """Where the next fetch starts: a week back from what we have, else the backfill start."""
    if last_price_date is not None:
        return last_price_date - REFRESH_OVERLAP
    return saxo_prices.since_for_backfill(first_needed, today, history_start)


def upsert_bars(bars: list[DailyBar]) -> int:
    return db.upsert_many(
        "daily_prices",
        [
            {
                "security_id": bar.security_id,
                "price_date": bar.price_date,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "currency": bar.currency,
                "source": bar.source,
                "fetched_at": datetime.now(UTC),
            }
            for bar in bars
        ],
        conflict_columns=("security_id", "price_date"),
    )


def upsert_broker_marks(bars: list[DailyBar]) -> int:
    """Store broker marks as the day's close; they win over Saxo or Yahoo closes (see the SQL)."""
    if not bars:
        return 0
    params = [
        {
            "security_id": bar.security_id,
            "price_date": bar.price_date,
            "close": bar.close,
            "currency": bar.currency,
            "source": bar.source,
        }
        for bar in bars
    ]
    with db.get_pool().connection() as conn, conn.cursor() as cur:
        cur.executemany(sql.UPSERT_BROKER_MARK, params)
        return cur.rowcount


def _set_status(
    security_id: int,
    source: str,
    *,
    first_needed: date | None,
    yahoo_symbol: str | None = None,
    error: str | None = None,
) -> None:
    db.execute(
        sql.UPSERT_PRICE_SOURCE,
        {
            "security_id": security_id,
            "source": source,
            "yahoo_symbol": yahoo_symbol,
            "first_needed": first_needed,
            "last_error": error,
        },
    )


def _sync_from_saxo(
    client: SaxoClient, security: dict[str, Any], since: date, today: date, connection_id: int
) -> tuple[int, FetchResult | None]:
    def store(result: FetchResult) -> None:
        connections.record_raw_payload(
            connection_id, result.endpoint, result.params, result.status_code, result.payload
        )

    rows, failure = saxo_prices.fetch_daily_bars(
        client, int(security["uic"]), str(security["asset_type"]), since=since, today=today, store=store
    )
    time.sleep(saxo_prices.REQUEST_PAUSE)  # between securities as well
    bars: list[DailyBar] = []
    for row in rows:
        bar = saxo_prices.map_bar(
            SaxoBar.model_validate(row), security_id=security["id"], currency=security["currency"]
        )
        if bar is not None and bar.price_date >= since:
            bars.append(bar)
    return upsert_bars(bars), failure


def _sync_from_yahoo(yahoo: YahooClient, security: dict[str, Any], since: date, today: date) -> tuple[int, str | None]:
    symbol = security.get("yahoo_symbol") or yahoo_mapping.yahoo_symbol(security["ticker"], security["mic"])
    if not symbol:
        return 0, None
    history = yahoo.fetch_daily(symbol, since, today)
    currency = history.currency or security["currency"]
    bars = yahoo_mapping.map_history(history.frame, security_id=security["id"], currency=currency)
    # Days the broker marked itself keep the broker's price.
    params = {"security_id": security["id"], "since": since}
    marked = {row["price_date"] for row in db.select(sql.SELECT_BROKER_MARK_DATES, params)}
    return upsert_bars([bar for bar in bars if bar.price_date not in marked]), symbol


def sync_prices(
    connection_id: int,
    *,
    client: SaxoClient | None = None,
    yahoo: YahooClient | None = None,
    today: date | None = None,
    security_ids: set[int] | None = None,
) -> PriceSyncReport:
    """Bring every security of the connection's broker up to date. Safe to rerun."""
    report = PriceSyncReport(connection_id=connection_id)
    today = today or datetime.now(UTC).date()
    history_start = date.fromisoformat(settings.saxo_history_start)
    status = connections.get_connection(connection_id)
    if status is None:
        raise ValueError(f"connection {connection_id} does not exist")
    # Only Saxo serves price history; every other broker's securities go straight to Yahoo.
    broker = status.broker
    securities = db.select(sql.SELECT_SECURITIES_FOR_PRICES, {"broker": broker})
    if security_ids is not None:
        securities = [row for row in securities if row["id"] in security_ids]
    owned_client = client is None and broker == mapping.BROKER
    if client is None and broker == mapping.BROKER:
        connection = connections.load_secrets(connection_id)
        if connection is None:
            raise ValueError(f"connection {connection_id} does not exist")
        client = client_for(connection)
    yahoo = yahoo or YahooClient()
    try:
        for security in securities:
            report.securities += 1
            since = fetch_since(security["last_price_date"], security["first_needed"], today, history_start)
            label = f"{security['ticker']}:{security['mic'] or '-'} ({security['id']})"
            source = security["source"]
            first_needed = security["first_needed"]
            if source in (None, "saxo") and client is not None:
                try:
                    count, failure = _sync_from_saxo(client, security, since, today, connection_id)
                except Exception as exc:  # network or mapping problem: keep going with the next security
                    report.errors.append(f"{label}: saxo {type(exc).__name__}: {str(exc)[:200]}")
                    _set_status(security["id"], "saxo", first_needed=first_needed, error=str(exc)[:500])
                    continue
                if failure is None:
                    report.saxo += 1
                    report.bars += count
                    _set_status(security["id"], "saxo", first_needed=first_needed)
                    continue
                if source == "saxo" or failure.status_code != 404:
                    message = f"HTTP {failure.status_code}: {str(failure.payload)[:200]}"
                    report.errors.append(f"{label}: saxo {message}")
                    _set_status(security["id"], "saxo", first_needed=first_needed, error=message)
                    continue
                # Saxo does not know the instrument (delisted or merged): fall through to Yahoo.
            try:
                count, symbol = _sync_from_yahoo(yahoo, security, since, today)
            except Exception as exc:
                message = f"{type(exc).__name__}: {str(exc)[:200]}"
                report.errors.append(f"{label}: yahoo {message}")
                _set_status(
                    security["id"],
                    "yahoo",
                    first_needed=first_needed,
                    yahoo_symbol=security.get("yahoo_symbol"),
                    error=message,
                )
                continue
            if symbol is None:
                report.unavailable += 1
                _set_status(
                    security["id"],
                    "none",
                    first_needed=first_needed,
                    error="not available from Saxo and no Yahoo symbol for the listing",
                )
                continue
            report.yahoo += 1
            report.bars += count
            _set_status(security["id"], "yahoo", first_needed=first_needed, yahoo_symbol=symbol)
    finally:
        if owned_client and client is not None:
            client.close()
        report.finished_at = datetime.now(UTC)
    return report


def price_status() -> list[dict[str, Any]]:
    rows = db.select(sql.SELECT_PRICE_STATUS)
    for row in rows:
        ticker, mic = row.pop("ticker"), row.pop("mic")
        row["full_ticker"] = f"{ticker}:{mic}" if mic else ticker
    return rows


def daily_prices(security_id: int, date_gte: date | None = None, date_lte: date | None = None) -> list[dict[str, Any]]:
    return db.select(sql.SELECT_DAILY_PRICES, {"security_id": security_id, "date_gte": date_gte, "date_lte": date_lte})
