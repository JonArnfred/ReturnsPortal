"""Yahoo Finance symbols from ticker and MIC, and daily bars from a yfinance history frame."""

from __future__ import annotations

import math
import re
from datetime import date
from decimal import Decimal
from typing import Any

from app.connectors.saxo.prices import normalize_currency
from app.domain.models import DailyBar

# ISO MIC -> Yahoo suffix. US listings have none.
YAHOO_SUFFIX: dict[str, str] = {
    "XNAS": "",
    "XNYS": "",
    "ARCX": "",
    "BATS": "",
    "XASE": "",
    "XCSE": ".CO",
    "XSTO": ".ST",
    "XHEL": ".HE",
    "XOSL": ".OL",
    "XETR": ".DE",
    "XFRA": ".F",
    "XLON": ".L",
    "XMIL": ".MI",
    "XAMS": ".AS",
    "XPAR": ".PA",
    "XBRU": ".BR",
    "XLIS": ".LS",
    "XMAD": ".MC",
    "XSWX": ".SW",
    "XWBO": ".VI",
    "XWAR": ".WA",
    "XTKS": ".T",
    "XTSE": ".TO",
    "XASX": ".AX",
    "XHKG": ".HK",
    "XTAE": ".TA",
    "XSES": ".SI",
    "XNZE": ".NZ",
}

_CLASS_SUFFIX = re.compile(r"^([A-Z0-9]+)([a-z])$")


def yahoo_symbol(ticker: str | None, mic: str | None) -> str | None:
    """``("NOVOb", "XCSE")`` -> ``NOVO-B.CO``; ``("BRK.B", "XNYS")`` -> ``BRK-B``; unknown MIC -> None."""
    if not ticker or mic is None or mic.upper() not in YAHOO_SUFFIX:
        return None
    base = ticker.strip()
    match = _CLASS_SUFFIX.match(base)
    if match:
        base = f"{match.group(1)}-{match.group(2).upper()}"
    base = base.replace(" ", "-").replace(".", "-").upper()
    return f"{base}{YAHOO_SUFFIX[mic.upper()]}"


def _decimal(value: Any) -> Decimal | None:
    """yfinance delivers numpy floats; the shortest repr is the decimal the source published."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return Decimal(repr(number))


def map_history(frame: Any, *, security_id: int, currency: str | None) -> list[DailyBar]:
    """A yfinance ``history`` frame (``auto_adjust=False``) into bars; rows without a close are skipped."""
    bars: list[DailyBar] = []
    for index, row in frame.iterrows():
        close = _decimal(row.get("Close"))
        if close is None:
            continue
        price_date = index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10])
        major, close_major = normalize_currency(currency, close)
        assert close_major is not None
        bars.append(
            DailyBar(
                security_id=security_id,
                price_date=price_date,
                open=normalize_currency(currency, _decimal(row.get("Open")))[1],
                high=normalize_currency(currency, _decimal(row.get("High")))[1],
                low=normalize_currency(currency, _decimal(row.get("Low")))[1],
                close=close_major,
                volume=_decimal(row.get("Volume")),
                currency=major,
                source="yahoo",
            )
        )
    return bars
