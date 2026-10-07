"""Reports over the PnL engine: the attribution table, unitized portfolio series, issues, rebuild."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from litestar import get, post
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import FromQuery, QueryParameter
from pydantic import BaseModel, Field

from app.openapi import standard_error_responses
from app.routes.ledger import PageMeta, _page
from app.services import dashboard_service, pnl_service


class PnlRow(BaseModel):
    """One position on one calendar day with its attribution (documentation/VISION.md 4.2)."""

    day: date
    portfolio_id: int
    portfolio_name: str
    position_kind: str = Field(description="security or cash.", examples=["security"])
    position_key: str = Field(description="Stable key of the position within the portfolio.", examples=["sec:12"])
    security_id: int | None
    security_name: str | None
    full_ticker: str | None = Field(description="ticker:MIC, or the currency for cash.", examples=["ROKU:XNAS"])
    currency: str = Field(description="Instrument currency, or the cash currency.")
    base_currency: str
    position_type: str = Field(description="long or short.", examples=["long"])
    quantity: Decimal = Field(description="Held at the close, on the split-adjusted basis of the price history.")
    quantity_prev: Decimal
    trade_quantity: Decimal = Field(description="Net traded on the day, same basis.")
    basis_factor: Decimal = Field(description="Raw ledger quantity times this equals quantity.")
    price: Decimal | None = Field(description="Carried close in the instrument currency; 1 for cash.")
    price_change: Decimal | None
    price_date: date | None = Field(description="Observation date of the carried price.")
    price_source: str | None = Field(description="close, ledger or cash.")
    fx: Decimal | None = Field(description="Base currency per unit of the instrument currency.")
    fx_change: Decimal | None
    execution_price: Decimal | None = Field(description="Volume-weighted price of the day's trades.")
    execution_fx: Decimal | None
    market_value_base: Decimal
    market_value_local: Decimal
    prev_market_value_base: Decimal
    trade_flow_base: Decimal = Field(description="Cost of the day's trades (buys positive), ex costs.")
    trade_flow_local: Decimal
    flow_base: Decimal = Field(description="All base money into the position; daily_pnl = ΔMV - flow exactly.")
    price_effect_base: Decimal
    price_effect_local: Decimal
    fx_effect_base: Decimal
    interaction_effect_base: Decimal
    dividend_effect_base: Decimal = Field(description="Dividends and lending income booked on the day.")
    dividend_effect_local: Decimal
    interest_effect_base: Decimal
    cost_effect_base: Decimal = Field(description="Commissions, fees, taxes and withholding tax (negative).")
    cost_effect_local: Decimal
    daily_pnl_base: Decimal
    daily_pnl_local: Decimal
    daily_return_pct: Decimal | None = Field(description="daily_pnl_base over |prior market value|, as a fraction.")
    constant_currency_return_pct: Decimal | None = Field(description="Local PnL at yesterday's FX over |prior value|.")
    total_pnl_base: Decimal = Field(description="Running sum of daily_pnl_base for the position.")
    total_pnl_local: Decimal


class PnlResponse(BaseModel):
    data: list[PnlRow]
    meta: PageMeta


class PortfolioDay(BaseModel):
    """One calendar day of unitized portfolio accounting (documentation/VISION.md 4.1)."""

    reporting_start_date: date | None = None

    day: date
    portfolio_id: int = Field(description="0 for all portfolios together.")
    portfolio_name: str
    base_currency: str
    nav: Decimal = Field(description="Positions plus cash at the close, in base currency.")
    positions_value: Decimal
    cash_value: Decimal
    nav_prev: Decimal
    flow: Decimal = Field(description="External flow: deposits minus withdrawals.")
    cumulative_cash_additions: Decimal = Field(
        description="Lifetime deposits minus withdrawals through this day, in base currency, including history "
        "before date filters and reporting start. Total sums the portfolios included in that day's NAV."
    )
    returns_base: Decimal = Field(description="Lifetime monetary return: NAV minus cumulative_cash_additions.")
    daily_pnl: Decimal = Field(description="nav - nav_prev - flow; equals the sum of the positions' daily PnL.")
    daily_return_pct: Decimal | None = Field(description="Time-weighted daily return, as a fraction.")
    unit_price: Decimal = Field(description="NAV per unit, 100 at inception.")
    units: Decimal
    cumulative_return_pct: Decimal
    drawdown_pct: Decimal = Field(description="Unit price relative to its running peak, as a fraction (≤ 0).")
    broker_value: Decimal | None = Field(description="Broker-reported account value on snapshot days.")


class SeriesSummary(BaseModel):
    first_day: date | None
    last_day: date | None
    days: int
    period_return_pct: Decimal | None = Field(description="Return over the returned slice, as a fraction.")
    annualized_return_pct: Decimal | None = Field(description="Only after 30 days; calendar-day basis.")
    max_drawdown_pct: Decimal | None
    nav: Decimal | None
    unit_price: Decimal | None
    cumulative_return_pct: Decimal | None = Field(description="Since inception, as a fraction.")


class PortfolioDaysResponse(BaseModel):
    portfolio_id: int
    data: list[PortfolioDay]
    summary: SeriesSummary


class IssueFxRate(BaseModel):
    """One currency held on a NAV-mismatch day, valued by both sides."""

    currency: str
    ecb_rate: Decimal = Field(description="Reporting currency per unit, the ECB rate the engine valued the day at.")
    ecb_rate_date: date | None = Field(description="Date of that ECB rate (forward-filled over non-fixing days).")
    broker_rate: Decimal | None = Field(
        description="Reporting currency per unit at the broker's own rate; null when the broker's rate is unknown."
    )
    broker_rate_date: date | None
    broker_quote_currency: str | None = Field(
        description="Currency the broker quotes its own rate in (IBKR: the account base, crossed into the "
        "reporting currency with the ECB rate its NAV is converted with)."
    )
    broker_quote_rate: Decimal | None = Field(description="The broker's rate as stated: quote currency per unit.")
    value_local: Decimal = Field(description="Engine holdings in this currency (securities and cash), local amount.")
    gap_fx: Decimal | None = Field(
        description="value_local x (ecb_rate - broker_rate): this currency's part of the issue's gap_fx."
    )


class IssueRow(BaseModel):
    id: int
    portfolio_id: int
    portfolio_name: str
    day: date
    kind: str = Field(examples=["nav_mismatch"])
    security_id: int | None
    security_name: str | None
    full_ticker: str | None
    currency: str | None
    amount: Decimal | None
    message: str
    created_at: datetime
    broker: str | None = Field(default=None, description="Broker of the portfolio's connection, e.g. ibkr or saxo.")
    gap_fx: Decimal | None = Field(
        default=None,
        description="NAV mismatches: part of the difference from valuing holdings at ECB rates instead of the "
        "broker's own FX rates. Null when the broker's rates are not known for every held currency.",
    )
    gap_cash: Decimal | None = Field(
        default=None, description="NAV mismatches: engine cash minus broker cash, both at the broker's FX rates."
    )
    gap_securities: Decimal | None = Field(
        default=None,
        description="NAV mismatches: engine securities minus broker securities at the broker's FX rates "
        "(prices and quantities). gap_fx + gap_cash + gap_securities equals amount.",
    )
    fx_rates: list[IssueFxRate] = Field(
        default_factory=list,
        description="NAV mismatches: ECB and broker FX rate per held currency, largest effect first.",
    )


class IssuesResponse(BaseModel):
    data: list[IssueRow]


class EngineStatusRow(BaseModel):
    portfolio_id: int
    portfolio_name: str
    first_day: date | None
    last_day: date | None
    position_rows: int
    issues: int


class RebuildResponse(BaseModel):
    portfolios: list[dict[str, Any]]
    started_at: str
    finished_at: str
    status: list[EngineStatusRow]


class DashboardPortfolio(BaseModel):
    reporting_start_date: date | None = None
    portfolio_id: int
    portfolio_name: str
    base_currency: str
    first_day: date | None
    last_day: date | None = Field(description="Latest calculated day available for this portfolio.")
    nav: Decimal | None
    daily_pnl: Decimal | None
    daily_return_pct: Decimal | None
    cumulative_return_pct: Decimal | None


class DashboardNavPoint(BaseModel):
    day: date
    nav: Decimal


class DashboardFx(BaseModel):
    currency: str
    effect: Decimal = Field(description="Summed FX effect in base currency, including cash.")


class DashboardResponse(BaseModel):
    as_of: date | None = Field(
        description="Latest shared valuation day, today included, with market observations or account activity; "
        "base-currency cash-only days need neither. Null when totals are unavailable."
    )
    intraday: bool = Field(
        description="True when as_of is today: its closes are the latest intraday prices until the markets close."
    )
    base_currency: str | None
    nav: Decimal | None
    daily_pnl: Decimal | None
    daily_return_pct: Decimal | None = Field(description="Summed PnL / summed prior NAV, as a fraction.")
    fx_effect_base: Decimal | None
    issue_count: int = Field(description="Data-quality findings from the latest rebuilds within each reporting period.")
    series: list[DashboardNavPoint]
    portfolios: list[DashboardPortfolio]
    fx_by_currency: list[DashboardFx]
    top: list[PnlRow]
    bottom: list[PnlRow]
    warnings: list[str]


@get(
    "/api/reports/dashboard",
    operation_id="getDashboard",
    summary="Dashboard from calculated portfolio results",
    description=(
        "Read-only snapshot of NAV history, daily PnL, FX attribution including cash, portfolio returns, "
        "five highest and lowest contributors, and recorded reconciliation findings. Uses the latest shared "
        "day of portfolios with calculated returns, today included once it has market observations (flagged "
        "as intraday); missing coverage is reported in warnings. Totals are "
        "unavailable for mixed base currencies. Does not sync brokers or rebuild data. Uses the same access "
        "policy as other report endpoints; no additional endpoint-specific authentication."
    ),
    responses={
        200: ResponseSpec(data_container=DashboardResponse, description="Stored results or an explicit empty state."),
        **standard_error_responses(),
    },
    tags=["Reports"],
    sync_to_thread=True,
)
def get_dashboard() -> DashboardResponse:
    return DashboardResponse.model_validate(dashboard_service.dashboard())


@get(
    "/api/reports/pnl",
    operation_id="listPnlRows",
    summary="Daily position attribution",
    description=(
        "One row per position per calendar day: quantities, carried price and FX, market value and the "
        "decomposition of the day's PnL into price, FX, interaction, dividend, interest and cost effects. "
        "Cash balances per currency are positions too. Paged; filters and sort are query parameters. Read-only."
    ),
    responses={
        200: ResponseSpec(data_container=PnlResponse, description="A page of attribution rows."),
        **standard_error_responses(),
    },
    tags=["Reports"],
    sync_to_thread=True,
)
def list_pnl_rows(
    page: FromQuery[int] = 1,
    per_page: FromQuery[int] = 100,
    order_by: FromQuery[str] = "day",
    order: FromQuery[str] = "desc",
    portfolio_id: FromQuery[int | None] = None,
    security_id: FromQuery[int | None] = None,
    position_kind: Annotated[
        str | None, QueryParameter(description="security or cash; anything else returns both.")
    ] = None,
    position_type: Annotated[
        str | None, QueryParameter(description="long or short; anything else returns both.")
    ] = None,
    date_gte: FromQuery[date | None] = None,
    date_lte: FromQuery[date | None] = None,
    search: FromQuery[str | None] = None,
    include_flat: Annotated[
        bool, QueryParameter(description="Also return days where a position is flat and idle.")
    ] = False,
) -> PnlResponse:
    filters = pnl_service.PnlFilter(
        portfolio_id=portfolio_id,
        security_id=security_id,
        position_kind=position_kind,
        position_type=position_type,
        date_gte=date_gte,
        date_lte=date_lte,
        search=search,
        active_only=not include_flat,
    )
    paging = _page(page, per_page, order_by, order)
    rows, total = pnl_service.list_pnl_rows(filters, paging)
    return PnlResponse(
        data=[PnlRow.model_validate(row) for row in rows],
        meta=PageMeta(
            total=total, page=paging.page, per_page=paging.per_page, order_by=paging.order_by, order=paging.order
        ),
    )


@get(
    "/api/reports/portfolio-days",
    operation_id="listPortfolioDays",
    summary="Unitized portfolio series",
    description=(
        "NAV, external flows, lifetime cumulative net cash additions and monetary return, daily PnL, units, "
        "unit price, cumulative return and drawdown per calendar day. Cash additions and monetary return "
        "retain history before date filters and each portfolio's reporting start. "
        "Without portfolio_id (or with 0) all portfolios are unitized together as 'Total'. Read-only."
    ),
    responses={
        200: ResponseSpec(data_container=PortfolioDaysResponse, description="Days oldest first with a summary."),
        **standard_error_responses(),
    },
    tags=["Reports"],
    sync_to_thread=True,
)
def list_portfolio_days(
    portfolio_id: FromQuery[int | None] = None,
    date_gte: FromQuery[date | None] = None,
    date_lte: FromQuery[date | None] = None,
) -> PortfolioDaysResponse:
    rows = pnl_service.portfolio_days(portfolio_id, date_gte, date_lte)
    return PortfolioDaysResponse(
        portfolio_id=portfolio_id or 0,
        data=[PortfolioDay.model_validate(row) for row in rows],
        summary=SeriesSummary.model_validate(pnl_service.series_summary(rows)),
    )


@get(
    "/api/reconciliation/issues",
    operation_id="listReconciliationIssues",
    summary="Issues recorded by the last rebuild",
    description=(
        "Data-quality findings of the PnL engine: missing or stale prices, missing FX, inferred splits, and "
        "days where the engine NAV differs from the broker's reported value, split into ECB-vs-broker FX, cash "
        "and securities where the broker's FX rates are known. Read-only."
    ),
    responses={
        200: ResponseSpec(data_container=IssuesResponse, description="Issues, newest day first."),
        **standard_error_responses(),
    },
    tags=["Reports"],
    sync_to_thread=True,
)
def list_reconciliation_issues() -> IssuesResponse:
    return IssuesResponse(data=[IssueRow.model_validate(row) for row in pnl_service.list_issues()])


@post(
    "/api/reports/rebuild",
    operation_id="rebuildPnl",
    summary="Rebuild the derived PnL tables",
    description=(
        "Runs the SQL engine for every portfolio from the ledger, prices and FX, replacing pnl_days, "
        "portfolio_days and reconciliation_issues. Synchronous; takes some seconds per portfolio."
    ),
    responses={
        200: ResponseSpec(data_container=RebuildResponse, description="Row counts per portfolio."),
        **standard_error_responses(),
    },
    tags=["Reports"],
    sync_to_thread=True,
)
def rebuild_pnl() -> RebuildResponse:
    report = pnl_service.rebuild_all()
    return RebuildResponse(
        **report, status=[EngineStatusRow.model_validate(row) for row in pnl_service.engine_status()]
    )


routes = [get_dashboard, list_pnl_rows, list_portfolio_days, list_reconciliation_issues, rebuild_pnl]
