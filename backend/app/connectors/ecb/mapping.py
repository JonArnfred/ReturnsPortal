"""Pure parsing of the ECB XML and crossing of euro rates to a base currency."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from xml.etree import ElementTree

from pydantic import BaseModel

NS = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
RATE_PLACES = Decimal("0.000000000001")


class EcbRate(BaseModel, frozen=True):
    rate_date: date
    currency: str
    units_per_eur: Decimal


class FxRate(BaseModel, frozen=True):
    """Base currency per one unit of ``currency`` (the engine's convention: always multiply)."""

    rate_date: date
    base_currency: str
    currency: str
    rate: Decimal
    source: str


def parse_feed(text: str) -> list[EcbRate]:
    """Every (day, currency) in the feed. Currencies ECB has dropped simply stop appearing."""
    root = ElementTree.fromstring(text)
    rates: list[EcbRate] = []
    for day_cube in root.iterfind(".//e:Cube[@time]", NS):
        rate_date = date.fromisoformat(day_cube.attrib["time"])
        for cube in day_cube.iterfind("e:Cube[@currency]", NS):
            rate = cube.attrib.get("rate")
            if not rate or rate == "N/A":
                continue
            rates.append(EcbRate(rate_date=rate_date, currency=cube.attrib["currency"], units_per_eur=Decimal(rate)))
    return rates


def cross_to_base(rates: Iterable[EcbRate], base_currency: str) -> list[FxRate]:
    """Cross each day's euro rates through EUR into ``base_currency`` per unit of every currency.

    ``base per X = (base per EUR) / (X per EUR)``. EUR itself becomes ``base per EUR`` and the base
    currency gets an explicit ``1`` row. A base currency that ECB does not publish yields nothing
    for that day (except when the base is EUR).
    """
    by_day: dict[date, dict[str, Decimal]] = {}
    for rate in rates:
        by_day.setdefault(rate.rate_date, {})[rate.currency] = rate.units_per_eur
    out: list[FxRate] = []
    for rate_date, quotes in sorted(by_day.items()):
        base_per_eur = Decimal(1) if base_currency == "EUR" else quotes.get(base_currency)
        if base_per_eur is None:
            continue
        out.append(
            FxRate(
                rate_date=rate_date,
                base_currency=base_currency,
                currency=base_currency,
                rate=Decimal(1),
                source="identity",
            )
        )
        if base_currency != "EUR":
            out.append(
                FxRate(
                    rate_date=rate_date,
                    base_currency=base_currency,
                    currency="EUR",
                    rate=_q(base_per_eur),
                    source="ecb",
                )
            )
        for currency, units_per_eur in quotes.items():
            if currency == base_currency or units_per_eur == 0:
                continue
            out.append(
                FxRate(
                    rate_date=rate_date,
                    base_currency=base_currency,
                    currency=currency,
                    rate=_q(base_per_eur / units_per_eur),
                    source="ecb",
                )
            )
    return out


def _q(value: Decimal) -> Decimal:
    return value.quantize(RATE_PLACES, rounding=ROUND_HALF_EVEN)
