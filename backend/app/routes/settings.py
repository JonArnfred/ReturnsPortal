"""Application settings changed from Setup: the reporting currency."""

from __future__ import annotations

import logging

from litestar import get, put
from litestar.exceptions import ValidationException
from litestar.openapi.datastructures import ResponseSpec
from pydantic import BaseModel, Field

from app.config import settings
from app.openapi import standard_error_responses
from app.services import settings_service

logger = logging.getLogger("returns-portal.settings")


class CurrencyOption(BaseModel):
    code: str = Field(examples=["EUR"])
    allowed: bool = Field(description="Whether the currency can be chosen now.")
    reason: str | None = Field(default=None, description="Why it cannot be chosen, when it cannot.")


class PortfolioCurrency(BaseModel):
    portfolio_id: int
    portfolio_name: str
    booked_currency: str = Field(description="Currency the portfolio's ledger is booked in.")
    built_currency: str | None = Field(description="Currency of the last PnL rebuild; null before the first.")


class ReportingCurrencySettings(BaseModel):
    currency: str = Field(description="The reporting currency every portfolio is booked in.", examples=["EUR"])
    default_currency: str = Field(description="REPORTING_CURRENCY from the environment, used until one is chosen.")
    options: list[CurrencyOption] = Field(description="Currencies with ECB reference rates, EUR included.")
    pending: bool = Field(description="True while portfolios are still being re-booked or rebuilt in the currency.")
    portfolios: list[PortfolioCurrency]
    task_id: str | None = Field(default=None, description="Recalculation task queued by this request, if any.")


class ReportingCurrencyUpdate(BaseModel):
    currency: str = Field(min_length=3, max_length=3, examples=["EUR"])


def _settings(task_id: str | None = None) -> ReportingCurrencySettings:
    currency = settings_service.reporting_currency()
    portfolios = settings_service.portfolio_currencies()
    return ReportingCurrencySettings(
        currency=currency,
        default_currency=settings.reporting_currency,
        options=[
            CurrencyOption(code=o.code, allowed=o.allowed, reason=o.reason) for o in settings_service.currency_options()
        ],
        pending=settings_service.recalculation_pending(currency, portfolios),
        portfolios=[PortfolioCurrency.model_validate(row) for row in portfolios],
        task_id=task_id,
    )


@get(
    "/api/settings/reporting-currency",
    operation_id="getReportingCurrency",
    summary="Reporting currency",
    description=(
        "The currency every portfolio is booked and reported in, the currencies it can be changed to, and whether "
        "a recalculation after a change is still running. Read-only."
    ),
    responses={
        200: ResponseSpec(data_container=ReportingCurrencySettings, description="Current setting and options."),
        **standard_error_responses(),
    },
    tags=["Settings"],
    sync_to_thread=True,
)
def get_reporting_currency() -> ReportingCurrencySettings:
    return _settings()


@put(
    "/api/settings/reporting-currency",
    operation_id="setReportingCurrency",
    summary="Change the reporting currency",
    description=(
        "Stores the reporting currency and queues the recalculation: FX rates crossed into it, every broker "
        "ledger re-mapped from its stored payloads (no broker requests), and the PnL rebuild. Reports show "
        "mixed currencies until it finishes; poll the GET endpoint for `pending`. 400 for a currency without "
        "ECB rates, or one a connected broker cannot be booked in (Saxo books in its client currency)."
    ),
    responses={
        200: ResponseSpec(data_container=ReportingCurrencySettings, description="Stored; recalculation queued."),
        **standard_error_responses(),
    },
    tags=["Settings"],
    sync_to_thread=True,
)
def set_reporting_currency(data: ReportingCurrencyUpdate) -> ReportingCurrencySettings:
    try:
        settings_service.set_reporting_currency(data.currency)
    except ValueError as exc:
        raise ValidationException(detail=str(exc)) from exc
    return _settings(task_id=_queue_recalculation())


def _queue_recalculation() -> str | None:
    """None when the task queue is down; the change then applies with the next manual refresh."""
    from app.tasks import apply_reporting_currency

    try:
        return str(apply_reporting_currency.delay().id)
    except Exception:
        logger.exception("Could not queue the reporting-currency recalculation")
        return None


routes = [get_reporting_currency, set_reporting_currency]
