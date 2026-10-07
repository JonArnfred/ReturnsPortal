"""Daily FX rates: coverage per currency and the crossed series."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from litestar import get
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import FromQuery
from pydantic import BaseModel, Field

from app.openapi import standard_error_responses
from app.services import fx_service, settings_service


class FxStatusRow(BaseModel):
    """Coverage of one currency against one base currency."""

    base_currency: str = Field(examples=["EUR"])
    currency: str = Field(examples=["USD"])
    first_needed: date | None = Field(description="First ledger date of any portfolio in this base currency.")
    first_date: date | None
    last_date: date | None
    days: int = Field(description="Published days stored.")
    last_rate: Decimal | None = Field(description="Base currency per one unit of the currency.")


class FxStatusResponse(BaseModel):
    data: list[FxStatusRow]


class FxRateRow(BaseModel):
    rate_date: date
    rate: Decimal = Field(description="Base currency per one unit of the currency.")
    source: str = Field(description="ecb or identity.")


class FxSeriesResponse(BaseModel):
    base_currency: str
    currency: str
    data: list[FxRateRow]


@get(
    "/api/fx/status",
    operation_id="listFxStatus",
    summary="FX coverage per currency",
    description="Every currency the ledger or securities use, with the stored rate coverage. Read-only.",
    responses={
        200: ResponseSpec(data_container=FxStatusResponse, description="One row per (base, currency)."),
        **standard_error_responses(),
    },
    tags=["Data"],
    sync_to_thread=True,
)
def list_fx_status() -> FxStatusResponse:
    return FxStatusResponse(data=[FxStatusRow.model_validate(row) for row in fx_service.fx_status()])


@get(
    "/api/fx",
    operation_id="listFxRates",
    summary="Daily FX series",
    description=(
        "ECB reference rates crossed through EUR into the base currency, one row per published day, "
        "oldest first. Gaps (weekends, holidays) are carried forward by the engine, not stored."
    ),
    responses={
        200: ResponseSpec(data_container=FxSeriesResponse, description="Rates, oldest first."),
        **standard_error_responses(),
    },
    tags=["Data"],
    sync_to_thread=True,
)
def list_fx_rates(
    currency: FromQuery[str],
    base_currency: FromQuery[str | None] = None,
    date_gte: FromQuery[date | None] = None,
    date_lte: FromQuery[date | None] = None,
) -> FxSeriesResponse:
    base = (base_currency or settings_service.reporting_currency()).upper()
    rows = fx_service.fx_series(base, currency.upper(), date_gte, date_lte)
    return FxSeriesResponse(
        base_currency=base,
        currency=currency.upper(),
        data=[FxRateRow.model_validate(row) for row in rows],
    )


routes = [list_fx_status, list_fx_rates]
