"""Daily price fetching and mapping, against the shapes seen live on 2026-09-19."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pandas as pd

from app.connectors.saxo import prices as saxo_prices
from app.connectors.saxo.client import SaxoClient
from app.connectors.saxo.dto import SaxoBar
from app.connectors.yahoo import mapping as yahoo
from app.services import price_service

BAR = {
    "Close": 1651.37,
    "High": 1679.82,
    "Interest": 0.0,
    "Low": 1581.0,
    "MarketTradingState": "Automated",
    "Open": 1595.0,
    "Time": "2026-09-18T00:00:00Z",
    "Volume": 830749.0,
}


def test_saxo_bar_maps_to_daily_bar_and_normalises_pence() -> None:
    bar = saxo_prices.map_bar(SaxoBar.model_validate(BAR), security_id=5, currency="USD")
    assert bar is not None and bar.price_date == date(2026, 9, 18) and bar.close == Decimal("1651.37")
    assert bar.open == Decimal("1595") and bar.volume == Decimal("830749") and bar.source == "saxo"
    pence_row = SaxoBar.model_validate({**BAR, "Close": 1482.6, "Open": None})
    pence = saxo_prices.map_bar(pence_row, security_id=5, currency="GBX")
    assert pence is not None and pence.currency == "GBP" and pence.close == Decimal("14.826") and pence.open is None
    assert saxo_prices.map_bar(SaxoBar.model_validate({**BAR, "Close": None}), security_id=5, currency="USD") is None


def test_backfill_and_refresh_windows() -> None:
    today = date(2026, 9, 19)
    assert saxo_prices.since_for_backfill(date(2021, 2, 26), today, date(2010, 1, 1)) == date(2021, 2, 12)
    assert saxo_prices.since_for_backfill(date(2009, 6, 1), today, date(2010, 1, 1)) == date(2010, 1, 1)
    assert saxo_prices.since_for_backfill(None, today, date(2010, 1, 1)) == date(2026, 8, 20)
    assert price_service.fetch_since(date(2026, 9, 18), date(2021, 1, 1), today, date(2010, 1, 1)) == date(2026, 9, 11)
    assert saxo_prices.bars_needed(date(2026, 9, 11), today) == 13
    assert saxo_prices.bars_needed(date(2010, 1, 1), today) == 1200


def _chart_handler(calls: list[dict[str, Any]]) -> Any:
    days = [date(2026, 9, d) for d in range(1, 13)]  # 12 "trading days", newest last

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        calls.append(params)
        if params["Uic"] == "404":
            return httpx.Response(404, json={"ErrorCode": "None", "Message": "Uic '404' is not valid."})
        count = int(params["Count"])
        upto = date.fromisoformat(params["Time"][:10]) if "Time" in params else days[-1]
        window = [d for d in days if d <= upto][-count:]
        data = [{**BAR, "Time": f"{d.isoformat()}T00:00:00Z", "Close": float(d.day)} for d in window]
        return httpx.Response(200, json={"Data": data})

    return handler


def test_saxo_paging_walks_back_until_the_window_is_covered_and_drops_the_overlap() -> None:
    calls: list[dict[str, Any]] = []
    with httpx.Client(transport=httpx.MockTransport(_chart_handler(calls))) as http:
        client = SaxoClient("t", "https://api.test/openapi", http=http)
        rows, failure = saxo_prices.fetch_daily_bars(
            client, 1, "Stock", since=date(2026, 9, 3), today=date(2026, 9, 12), page_size=5, pause=0
        )
        assert failure is None
        assert [row["Time"][:10] for row in rows] == [f"2026-09-{d:02d}" for d in range(1, 13)]
        assert [c.get("Mode") for c in calls] == [None, "UpTo", "UpTo"] and calls[1]["Time"] == "2026-09-08T00:00:00Z"
        rows, failure = saxo_prices.fetch_daily_bars(
            client, 404, "Stock", since=date(2026, 9, 3), today=date(2026, 9, 12)
        )
        assert rows == [] and failure is not None and failure.status_code == 404


def test_yahoo_symbols() -> None:
    assert yahoo.yahoo_symbol("NOVOb", "XCSE") == "NOVO-B.CO"
    assert yahoo.yahoo_symbol("BRK.B", "XNYS") == "BRK-B"
    assert yahoo.yahoo_symbol("ACME", "XNAS") == "ACME"
    assert yahoo.yahoo_symbol("4396", "XTKS") == "4396.T"
    assert yahoo.yahoo_symbol("SHEL", "XLON") == "SHEL.L"
    assert yahoo.yahoo_symbol("20376873", None) is None
    assert yahoo.yahoo_symbol("ABC", "XXXX") is None


def test_yahoo_history_frame_maps_and_skips_missing_closes() -> None:
    index = pd.DatetimeIndex([datetime(2021, 6, d, tzinfo=UTC) for d in (16, 17, 18)])
    frame = pd.DataFrame(
        {
            "Open": [58.0, 60.0, 61.0],
            "High": [60.0, 63.0, 62.0],
            "Low": [57.5, 59.0, 60.0],
            "Close": [59.02, 62.14, float("nan")],
            "Adj Close": [59.02, 62.14, float("nan")],
            "Volume": [100, 200, 0],
        },
        index=index,
    )
    bars = yahoo.map_history(frame, security_id=24, currency="GBp")
    assert [bar.price_date for bar in bars] == [date(2021, 6, 16), date(2021, 6, 17)]
    assert bars[0].close == Decimal("0.5902") and bars[0].currency == "GBP" and bars[0].source == "yahoo"
    assert bars[1].volume == Decimal("200")
