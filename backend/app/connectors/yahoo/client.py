"""Thin wrapper over yfinance so the price service can be tested without the network."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger("returns-portal.yahoo")


@dataclass
class YahooHistory:
    symbol: str
    currency: str | None
    frame: Any  # pandas.DataFrame from yfinance, columns Open/High/Low/Close/Adj Close/Volume


class YahooClient:
    """Daily history through yfinance, which handles Yahoo's cookie and crumb handshake."""

    def fetch_daily(self, symbol: str, since: date, until: date | None = None) -> YahooHistory:
        import yfinance as yf

        logging.getLogger("yfinance").setLevel(logging.ERROR)
        ticker = yf.Ticker(symbol)
        end = (until or date.today()) + timedelta(days=1)
        frame = ticker.history(
            start=since.isoformat(), end=end.isoformat(), interval="1d", auto_adjust=False, actions=False
        )
        currency: str | None = None
        try:
            currency = ticker.fast_info.get("currency")
        except Exception:  # fast_info raises for unknown symbols; the frame is then empty as well
            currency = None
        if frame is None or len(frame) == 0:
            raise LookupError(f"Yahoo returned no daily history for {symbol}")
        return YahooHistory(symbol=symbol, currency=currency, frame=frame)
