"""Daily prices: per-security source status and the bars themselves."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from litestar import get
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import FromQuery
from pydantic import BaseModel, Field

from app.openapi import standard_error_responses
from app.services import price_service


class PriceStatusRow(BaseModel):
    """One security's price coverage."""

    security_id: int
    security_name: str | None
    full_ticker: str = Field(examples=["ROKU:XNAS"])
    asset_type: str
    currency: str | None = Field(description="Currency of the stored bars.")
    source: str = Field(description="saxo, yahoo or none.", examples=["saxo"])
    yahoo_symbol: str | None
    first_needed: date | None = Field(description="First ledger date of the security.")
    last_needed: date | None = Field(description="Last ledger date of the security.")
    held: bool = Field(description="In the latest broker position snapshot.")
    first_price_date: date | None
    last_price_date: date | None
    last_close: Decimal | None
    bars: int
    last_fetched_at: datetime | None
    last_error: str | None


class PriceStatusResponse(BaseModel):
    data: list[PriceStatusRow]


class DailyPriceRow(BaseModel):
    price_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: Decimal | None
    currency: str | None
    source: str


class DailyPricesResponse(BaseModel):
    security_id: int
    data: list[DailyPriceRow]


@get(
    "/api/prices/status",
    operation_id="listPriceStatus",
    summary="Price coverage per security",
    description=(
        "Which source each security's daily prices come from, how far they reach, and the last error. Read-only."
    ),
    responses={
        200: ResponseSpec(data_container=PriceStatusResponse, description="One row per security."),
        **standard_error_responses(),
    },
    tags=["Data"],
    sync_to_thread=True,
)
def list_price_status() -> PriceStatusResponse:
    return PriceStatusResponse(data=[PriceStatusRow.model_validate(row) for row in price_service.price_status()])


@get(
    "/api/prices",
    operation_id="listDailyPrices",
    summary="Daily prices of a security",
    description=(
        "Split-adjusted daily OHLCV in the instrument currency, oldest first, optionally limited to a date range."
    ),
    responses={
        200: ResponseSpec(data_container=DailyPricesResponse, description="Bars, oldest first."),
        **standard_error_responses(),
    },
    tags=["Data"],
    sync_to_thread=True,
)
def list_daily_prices(
    security_id: FromQuery[int], date_gte: FromQuery[date | None] = None, date_lte: FromQuery[date | None] = None
) -> DailyPricesResponse:
    rows = price_service.daily_prices(security_id, date_gte, date_lte)
    return DailyPricesResponse(security_id=security_id, data=[DailyPriceRow.model_validate(row) for row in rows])


routes = [list_price_status, list_daily_prices]
