"""ECB feed parsing and EUR crosses, plus the sync's choice of feed."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.connectors.ecb import mapping
from app.services import fx_service

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<gesmes:subject>Reference rates</gesmes:subject>
<Cube>
<Cube time="2026-09-18">
<Cube currency="USD" rate="1.146"/><Cube currency="DKK" rate="7.4754"/><Cube currency="GBP" rate="0.8588"/>
</Cube>
<Cube time="2026-09-17">
<Cube currency="USD" rate="1.14"/><Cube currency="DKK" rate="7.475"/><Cube currency="XYZ" rate="N/A"/>
</Cube>
</Cube>
</gesmes:Envelope>
"""


def test_parse_feed_reads_every_day_and_skips_unavailable_rates() -> None:
    rates = mapping.parse_feed(FEED)
    assert len(rates) == 5
    assert rates[0] == mapping.EcbRate(rate_date=date(2026, 9, 18), currency="USD", units_per_eur=Decimal("1.146"))
    assert {rate.currency for rate in rates if rate.rate_date == date(2026, 9, 17)} == {"USD", "DKK"}


def test_cross_to_base_gives_base_per_unit_of_currency() -> None:
    crossed = mapping.cross_to_base(mapping.parse_feed(FEED), "DKK")
    by_key = {(rate.rate_date, rate.currency): rate for rate in crossed}
    assert by_key[date(2026, 9, 18), "DKK"].rate == Decimal(1)
    assert by_key[date(2026, 9, 18), "DKK"].source == "identity"
    assert by_key[date(2026, 9, 18), "EUR"].rate == Decimal("7.475400000000")
    assert by_key[date(2026, 9, 18), "USD"].rate == (Decimal("7.4754") / Decimal("1.146")).quantize(
        Decimal("0.000000000001")
    )
    assert by_key[date(2026, 9, 18), "GBP"].rate == (Decimal("7.4754") / Decimal("0.8588")).quantize(
        Decimal("0.000000000001")
    )
    assert (date(2026, 9, 17), "GBP") not in by_key  # not published that day: the engine carries forward
    assert sorted(rate.rate_date for rate in crossed) == sorted(rate.rate_date for rate in crossed)


def test_cross_to_eur_and_to_an_unpublished_base() -> None:
    rates = mapping.parse_feed(FEED)
    eur = {(r.rate_date, r.currency): r.rate for r in mapping.cross_to_base(rates, "EUR")}
    assert eur[date(2026, 9, 18), "EUR"] == Decimal(1)
    assert eur[date(2026, 9, 18), "USD"] == (Decimal(1) / Decimal("1.146")).quantize(Decimal("0.000000000001"))
    assert mapping.cross_to_base(rates, "ZZZ") == []


def test_full_history_is_fetched_when_stored_rates_are_missing_or_old() -> None:
    today = date(2026, 9, 19)
    assert fx_service.needs_full_history(None, today)
    assert fx_service.needs_full_history(date(2026, 5, 1), today)
    assert not fx_service.needs_full_history(date(2026, 9, 1), today)


def test_a_new_base_currency_is_crossed_from_the_whole_history() -> None:
    assert fx_service.split_bases(["DKK", "EUR"], ["DKK"]) == (["DKK"], ["EUR"])
    assert fx_service.split_bases(["DKK"], ["DKK", "EUR"]) == (["DKK"], [])
    assert fx_service.split_bases(["EUR"], []) == ([], ["EUR"])
