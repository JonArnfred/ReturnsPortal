"""Daily bars from Saxo's ``chart/v3/charts`` (verified 2026-09-19).

``Horizon=1440`` is one bar per trading day, split-adjusted, in the instrument currency. Without
``Mode`` the newest ``Count`` bars (at most 1200) come back; older bars are paged with
``Mode=UpTo`` and ``Time`` set to the oldest bar seen, which is returned again and must be
dropped. Instruments Saxo no longer knows answer 404 ``Uic '...' is not valid``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.connectors.saxo.client import FetchResult, SaxoClient
from app.connectors.saxo.dto import SaxoBar
from app.domain.models import DailyBar

CHART_ENDPOINT = "chart/v3/charts"
DAILY_HORIZON = 1440
MAX_COUNT = 1200
MAX_PAGES = 12  # 12 x 1200 trading days is about 47 years
# The chart endpoint rate-limits bursts; a short pause between requests keeps a full run under it.
REQUEST_PAUSE = 0.4

# Minor-unit quotes are normalised to the major currency so prices and FX agree. Saxo says GBX,
# Yahoo says GBp (which must not be uppercased into the major currency).
MINOR_UNITS = {"GBX": "GBP", "GBP": "GBP", "ZAC": "ZAR", "ILA": "ILS"}
MINOR_SPELLINGS = {"GBp": "GBX", "ZAc": "ZAC", "ILa": "ILA"}


def bars_needed(since: date, today: date) -> int:
    """Bars to ask for on the first page: enough calendar days plus a margin, capped at the maximum."""
    return max(10, min(MAX_COUNT, (today - since).days + 5))


def fetch_daily_bars(
    client: SaxoClient,
    uic: int,
    asset_type: str,
    *,
    since: date,
    today: date,
    store: Callable[[FetchResult], None] | None = None,
    page_size: int = MAX_COUNT,
    pause: float = REQUEST_PAUSE,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict[str, Any]], FetchResult | None]:
    """Raw bars from ``since`` to the newest, oldest first; the failing response when Saxo refused."""
    count = min(page_size, bars_needed(since, today))
    rows: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    for page_number in range(MAX_PAGES):
        if pause and page_number:
            sleep(pause)
        params: dict[str, Any] = {"Uic": uic, "AssetType": asset_type, "Horizon": DAILY_HORIZON, "Count": count}
        if cursor:
            params.update({"Mode": "UpTo", "Time": cursor})
        result = client.fetch(CHART_ENDPOINT, params)
        if store:
            store(result)
        if not result.ok:
            return sorted(rows.values(), key=lambda row: str(row["Time"])), result
        page = [row for row in result.data if isinstance(row, dict) and row.get("Time")]
        for row in page:
            rows.setdefault(str(row["Time"]), row)
        if not page or len(page) < count:
            break
        oldest = str(page[0]["Time"])
        if oldest[:10] <= since.isoformat() or oldest == cursor:
            break
        cursor = oldest
        count = page_size
    return sorted(rows.values(), key=lambda row: str(row["Time"])), None


def normalize_currency(currency: str | None, value: Decimal | None) -> tuple[str | None, Decimal | None]:
    """GBX and other minor-unit quotes become the major currency; everything else passes through."""
    raw = currency or ""
    code = MINOR_SPELLINGS.get(raw, raw.upper())
    minor = (code in MINOR_UNITS and code != raw.upper()) or code in ("GBX", "ZAC", "ILA")
    if not minor:
        return currency, value
    return MINOR_UNITS[code], (value / 100 if value is not None else None)


def map_bar(row: SaxoBar, *, security_id: int, currency: str | None) -> DailyBar | None:
    if row.close is None:
        return None
    major, close = normalize_currency(currency, row.close)
    assert close is not None
    return DailyBar(
        security_id=security_id,
        price_date=row.time.date(),
        open=normalize_currency(currency, row.open)[1],
        high=normalize_currency(currency, row.high)[1],
        low=normalize_currency(currency, row.low)[1],
        close=close,
        volume=row.volume,
        currency=major,
        source="saxo",
    )


def since_for_backfill(first_needed: date | None, today: date, history_start: date, margin_days: int = 14) -> date:
    """Earliest bar a first fetch must cover: a margin before the first ledger row, else recent only."""
    start = first_needed - timedelta(days=margin_days) if first_needed else today - timedelta(days=30)
    return max(start, history_start)
