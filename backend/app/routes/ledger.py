"""Read endpoints over the ledger and broker snapshots: transactions, positions, cash movements."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from litestar import get, patch
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import FromPath, FromQuery, QueryParameter
from pydantic import BaseModel, Field, field_validator

from app.openapi import standard_error_responses
from app.services import ledger_queries as queries
from app.services import order_service, portfolio_service, position_service


class PageMeta(BaseModel):
    total: int = Field(description="Rows matching the filters before paging.", examples=[3120])
    page: int = Field(description="1-based page number.", examples=[1])
    per_page: int = Field(description="Rows per page.", examples=[100])
    order_by: str = Field(description="Applied sort column.", examples=["trade_date"])
    order: str = Field(description="asc or desc.", examples=["desc"])


class TransactionRow(BaseModel):
    id: int
    trade_date: date
    value_date: date | None
    kind: str = Field(description="Ledger kind, e.g. trade, dividend, deposit.", examples=["trade"])
    portfolio_id: int
    portfolio_name: str
    account_label: str | None = Field(description="Broker account id and currency.", examples=["1234567/2 (USD)"])
    security_name: str | None
    full_ticker: str | None = Field(description="ticker:MIC when known.", examples=["ROKU:XNAS"])
    security_currency: str | None
    quantity: Decimal | None
    price: Decimal | None
    currency: str
    amount_local: Decimal
    account_currency: str | None
    amount_account: Decimal | None
    base_currency: str
    amount_base: Decimal | None
    fx_rate_base: Decimal | None
    description: str | None
    related_ref: str | None
    provisional: bool = Field(
        default=False,
        description=(
            "Executed at the broker but not yet booked: taken from the order audit, replaced by the booked trade."
        ),
    )


class TransactionsResponse(BaseModel):
    data: list[TransactionRow]
    meta: PageMeta


class PositionRow(BaseModel):
    """One holding episode of a security in a portfolio, from the positions table."""

    id: int
    portfolio_id: int
    portfolio_name: str
    security_id: int
    security_name: str | None
    full_ticker: str = Field(examples=["ROKU:XNAS"])
    asset_type: str
    currency: str | None = Field(description="Instrument currency.")
    base_currency: str
    position_type: str = Field(description="long or short.", examples=["long"])
    status: str = Field(description="open or closed.", examples=["open"])
    reporting_start_date: date | None = None
    opened: date
    closed: date | None
    quantity: Decimal
    trades: int = Field(description="Number of trades within the reporting period.")
    current_price: Decimal | None = Field(
        description="Latest broker mark for open positions, or the engine close when that is newer."
    )
    avg_buy_price: Decimal | None = Field(
        description="Lifetime split-adjusted average buy price in instrument currency."
    )
    avg_sell_price: Decimal | None
    value_base: Decimal = Field(description="Current market value in base currency; zero when closed.")
    invested_base: Decimal | None = Field(
        description="Absolute opening value plus reporting-period purchases and their commissions, fees and taxes. "
        "Null when the opening valuation is unavailable."
    )
    dividends_base: Decimal = Field(description="Dividends net of withholding tax plus lending income.")
    costs_base: Decimal = Field(description="Commissions, fees and taxes attributed to the position (negative).")
    return_base: Decimal | None = Field(
        description="Period gain: current value minus opening value plus subsequent trade cash flows, "
        "dividends and costs."
    )
    roi_pct: Decimal | None = Field(description="return_base / invested_base, as a fraction.")
    annualized_days_pct: Decimal | None
    annualized_months_pct: Decimal | None
    pct_aum: Decimal | None = Field(description="Share of total account value across portfolios.")
    pct_portfolio: Decimal | None = Field(description="Share of the portfolio's open position value.")
    notes: list[str]


class PositionsResponse(BaseModel):
    data: list[PositionRow]
    meta: PageMeta


class ShareStats(BaseModel):
    buys: int = Field(description="Number of buy trades.")
    shares_bought: Decimal = Field(description="Shares bought, on today's split-adjusted basis.")
    sells: int
    shares_sold: Decimal
    current: Decimal = Field(description="Shares held now; zero when closed.")


class ReturnsBlock(BaseModel):
    """Return of the position in one currency."""

    currency: str = Field(examples=["USD"])
    opening_value: Decimal | None = Field(
        default_factory=lambda: Decimal(0),
        description="Signed value carried into the reporting period; null if unavailable.",
    )
    total_cost: Decimal = Field(description="Cash paid for purchases, negative.")
    total_revenue: Decimal = Field(description="Cash received from sales.")
    value: Decimal | None = Field(description="Current market value; zero when closed, null without a valuation.")
    dividends: Decimal = Field(description="Dividends net of withholding tax plus lending income.")
    costs: Decimal = Field(description="Commissions, fees and taxes, negative.")
    return_amount: Decimal | None = Field(
        description="value - opening_value + total_revenue + total_cost + dividends + costs; null without valuation."
    )
    roi_pct: Decimal | None = Field(
        description="return_amount over absolute opening value plus purchases and buy-side costs, as a fraction."
    )
    annualized_days_pct: Decimal | None
    annualized_months_pct: Decimal | None


class PositionTrade(BaseModel):
    trade_date: date
    kind: str = Field(description="buy, sell or corporate_action.", examples=["buy"])
    quantity: Decimal = Field(description="Signed quantity as booked, before later splits.")
    price: Decimal | None = Field(description="Execution price as booked.")
    adjusted_price: Decimal | None = Field(description="Execution price on today's split-adjusted basis.")
    currency: str
    amount_local: Decimal
    amount_base: Decimal


class PositionSeriesPoint(BaseModel):
    date: date
    quantity: Decimal = Field(description="Split-adjusted shares held at the close of the day.")
    close: Decimal = Field(description="Split-adjusted close in the instrument currency.")
    market_value: Decimal = Field(description="quantity times close, in the instrument currency.")


class PricePoint(BaseModel):
    date: date
    close: Decimal = Field(description="Split-adjusted close in the instrument currency.")


class PositionDetail(BaseModel):
    """One position with its trades and a daily series for charts."""

    id: int
    portfolio_id: int
    portfolio_name: str
    security_id: int
    security_name: str | None
    full_ticker: str = Field(examples=["ANET:XNYS"])
    asset_type: str
    currency: str | None = Field(description="Instrument currency.")
    base_currency: str
    position_type: str
    status: str = Field(description="open or closed.")
    reporting_start_date: date | None = None
    original_cost_local: Decimal = Field(description="Lifetime acquisition cash, negative, in instrument currency.")
    original_cost_base: Decimal = Field(description="Lifetime acquisition cash, negative, in base currency.")
    opened: date = Field(description="First trade.")
    closed: date | None = Field(description="The trade that brought the quantity to zero, when closed.")
    current_price: Decimal | None
    price_date: date | None = Field(description="Date of the broker mark or engine close behind current_price.")
    shares: ShareStats
    returns_local: ReturnsBlock
    returns_base: ReturnsBlock
    trades: list[PositionTrade] = Field(description="Oldest first.")
    series: list[PositionSeriesPoint] = Field(
        description="Daily within the reporting period, including carried-in shares; ends at the closing date."
    )
    price_history: list[PricePoint] = Field(
        description="Daily closes from five years ago (or the opening date, if earlier) to today, for price context."
    )
    notes: list[str]


class CashBalance(BaseModel):
    currency: str = Field(examples=["USD"])
    amount: Decimal = Field(description="Cash held in that currency account, in the account currency.")


class PortfolioAccount(BaseModel):
    id: int = Field(description="Internal account id, used by the transactions `account` filter.")
    account_id: str | None = Field(description="Broker account number.", examples=["1234567/2"])
    currency: str | None
    label: str = Field(description="Account number and currency.", examples=["1234567/2 (USD)"])
    active: bool


class PortfolioCard(BaseModel):
    """One portfolio with its latest broker snapshot and the open positions derived from the ledger."""

    id: int
    name: str = Field(description="Name to show: the custom display name when set, else the broker name.")
    broker_name: str = Field(description="Name reported by the broker.")
    display_name: str | None = Field(description="User-chosen name, null when the broker name is used.")
    reporting_start_date: date | None = Field(
        default=None, description="Inclusive reporting boundary; null means full history."
    )
    base_currency: str = Field(examples=["EUR"])
    broker: str | None = Field(description="saxo or ibkr; null when the portfolio has no connection.")
    environment: str | None = Field(description="live or sim.")
    connection_status: str | None = Field(description="connected, expired or error.")
    last_sync_finished_at: datetime | None
    snapshot_date: date | None = Field(description="Date of the broker snapshot the values come from.")
    open_positions: int = Field(description="Number of open holding episodes.")
    positions_value_base: Decimal = Field(description="Market value of the open positions in base currency.")
    cash_base: Decimal | None = Field(description="Broker cash balance across currency accounts, in base currency.")
    total_value_base: Decimal | None = Field(description="Broker total account value in base currency.")
    unbooked_base: Decimal | None = Field(
        description=(
            "Executed trades the broker has not booked to cash yet, in base currency; counted in total_value_base "
            "but in neither cash nor positions. Null when the broker reports no such figure."
        )
    )
    unexplained_base: Decimal | None = Field(
        description=(
            "total_value_base minus cash_base, positions_value_base and unbooked_base; accrued items and rounding."
        )
    )
    cash_by_currency: list[CashBalance] = Field(description="Non-zero cash balances per currency account.")
    accounts: list[PortfolioAccount] = Field(description="Broker accounts behind the portfolio.")


class PortfoliosResponse(BaseModel):
    data: list[PortfolioCard]


class OrderRow(BaseModel):
    """One broker order in its latest known state."""

    id: int
    broker_order_id: str
    portfolio_id: int
    portfolio_name: str
    account_label: str | None = Field(description="Broker account id and currency.", examples=["1234567/2 (USD)"])
    security_id: int | None = Field(description="Null when the instrument is unknown to the securities table.")
    security_name: str | None
    full_ticker: str | None = Field(description="ticker:MIC when known.", examples=["ROKU:XNAS"])
    asset_type: str | None
    instrument_symbol: str | None = Field(description="Symbol as the broker reported it on the order.")
    status: str = Field(description="working, filled, cancelled, expired, rejected or other.", examples=["working"])
    broker_status: str | None = Field(description="The broker's own status word.", examples=["Working"])
    is_open: bool = Field(description="True when the broker listed the order as working at the latest sync.")
    buy_sell: str | None = Field(description="buy or sell.")
    order_type: str | None = Field(examples=["Limit"])
    duration: str | None = Field(examples=["GoodTillCancel"])
    quantity: Decimal | None
    filled_quantity: Decimal | None
    price: Decimal | None = Field(description="Limit or stop price in the instrument currency.")
    average_fill_price: Decimal | None
    currency: str | None
    placed_at: datetime | None
    last_activity_at: datetime | None
    expires_at: datetime | None
    order_relation: str | None = Field(description="StandAlone, IfDoneMaster, IfDoneSlave or Oco.")


class OrdersResponse(BaseModel):
    data: list[OrderRow]
    meta: PageMeta


class PortfolioUpdate(BaseModel):
    reporting_start_date: date | None = Field(
        default=None,
        description="Inclusive start of portfolio reporting. Null restores full history; omitted leaves it unchanged.",
        examples=["2024-01-01"],
    )

    @field_validator("reporting_start_date")
    @classmethod
    def validate_start_date(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("Reporting start date cannot be in the future.")
        return value

    display_name: str | None = Field(
        default=None,
        max_length=80,
        description="Custom name shown throughout the app. Null or blank restores the broker name.",
        examples=["Saxo pension"],
    )


class CashMovementRow(BaseModel):
    id: int
    trade_date: date
    value_date: date | None
    kind: str = Field(description="deposit, withdrawal, transfer, or conversion.", examples=["conversion"])
    portfolio_name: str
    from_account: str | None
    from_currency: str | None
    from_amount: Decimal | None = Field(description="Negative amount leaving the source account.")
    to_account: str | None
    to_currency: str | None
    to_amount: Decimal | None
    rate: Decimal | None = Field(description="Units of target currency per unit of source currency for conversions.")
    base_currency: str
    amount_base: Decimal | None
    description: str | None


class CashMovementsResponse(BaseModel):
    data: list[CashMovementRow]
    meta: PageMeta


def _page(page: int, per_page: int, order_by: str, order: str) -> queries.Page:
    return queries.Page(
        page=max(1, page), per_page=max(1, min(per_page, queries.MAX_PER_PAGE)), order_by=order_by, order=order
    )


@get(
    "/api/ledger/transactions",
    operation_id="listTransactions",
    summary="List ledger transactions",
    description=(
        "Paged, filtered ledger rows (trades, dividends, fees, cash flows). Read-only. "
        "`kinds` is a comma-separated list of ledger kinds; unknown kinds are ignored."
    ),
    responses={
        200: ResponseSpec(data_container=TransactionsResponse, description="Ledger rows and paging metadata."),
        **standard_error_responses(),
    },
    tags=["Investments"],
    sync_to_thread=True,
)
def list_transactions(
    page: FromQuery[int] = 1,
    per_page: FromQuery[int] = 100,
    order_by: FromQuery[str] = "trade_date",
    order: FromQuery[str] = "desc",
    kinds: Annotated[str | None, QueryParameter(description="Comma-separated ledger kinds.")] = None,
    portfolio_id: FromQuery[int | None] = None,
    account: Annotated[
        int | None, QueryParameter(description="Broker account id (PortfolioCard.accounts[].id).")
    ] = None,
    trade_type: Annotated[
        str | None, QueryParameter(description="buy, sell or corporate_action; other values are ignored.")
    ] = None,
    date_gte: FromQuery[date | None] = None,
    date_lte: FromQuery[date | None] = None,
    search: FromQuery[str | None] = None,
) -> TransactionsResponse:
    filters = queries.TransactionFilter(
        kinds=tuple(kind.strip() for kind in (kinds or "").split(",") if kind.strip()),
        portfolio_id=portfolio_id,
        account=account,
        trade_type=trade_type,
        date_gte=date_gte,
        date_lte=date_lte,
        search=search,
    )
    paging = _page(page, per_page, order_by, order)
    rows, total = queries.list_transactions(filters, paging)
    return TransactionsResponse(
        data=[TransactionRow.model_validate(row) for row in rows],
        meta=PageMeta(
            total=total, page=paging.page, per_page=paging.per_page, order_by=paging.order_by, order=paging.order
        ),
    )


@get(
    "/api/positions",
    operation_id="listPositions",
    summary="List positions",
    description=(
        "Holding episodes from the positions table (rebuilt from the ledger after every ingest), open and "
        "closed, with split-adjusted average prices, dividends, return, ROI and annualized return. Open "
        "positions are valued at the latest broker snapshot. Read-only."
    ),
    responses={
        200: ResponseSpec(data_container=PositionsResponse, description="Open positions."),
        **standard_error_responses(),
    },
    tags=["Investments"],
    sync_to_thread=True,
)
def list_positions() -> PositionsResponse:
    rows = position_service.list_positions()
    return PositionsResponse(
        data=[PositionRow.model_validate(row) for row in rows],
        meta=PageMeta(total=len(rows), page=1, per_page=max(len(rows), 1), order_by="value_base", order="desc"),
    )


@get(
    "/api/positions/{position_id:int}",
    operation_id="getPositionDetail",
    summary="Position detail",
    description=(
        "One position: share counts, returns in the instrument and base currency, its trades, a daily "
        "series of split-adjusted quantity, close and market value over the holding, and up to five years "
        "of daily closes for price context. Read-only."
    ),
    responses={
        200: ResponseSpec(data_container=PositionDetail, description="The position."),
        **standard_error_responses(),
    },
    tags=["Investments"],
    sync_to_thread=True,
)
def get_position_detail(position_id: FromPath[int]) -> PositionDetail:
    detail = position_service.position_detail(position_id)
    if detail is None:
        raise NotFoundException(detail=f"position {position_id} does not exist")
    return PositionDetail.model_validate(detail)


@get(
    "/api/portfolios",
    operation_id="listPortfolios",
    summary="List portfolios",
    description=(
        "One card per portfolio: broker cash and total value from the latest snapshot, plus the number and "
        "value of open positions derived from the ledger. Read-only."
    ),
    responses={
        200: ResponseSpec(data_container=PortfoliosResponse, description="Portfolios in creation order."),
        **standard_error_responses(),
    },
    tags=["Investments"],
    sync_to_thread=True,
)
def list_portfolios() -> PortfoliosResponse:
    return PortfoliosResponse(data=[PortfolioCard.model_validate(row) for row in portfolio_service.list_portfolios()])


@get(
    "/api/orders",
    operation_id="listOrders",
    summary="List orders",
    description=(
        "Every broker order known to the app, working and historical, one row per order in its latest state. "
        "Working orders first, then newest placed first. Read-only."
    ),
    responses={
        200: ResponseSpec(data_container=OrdersResponse, description="Orders, working first."),
        **standard_error_responses(),
    },
    tags=["Investments"],
    sync_to_thread=True,
)
def list_orders() -> OrdersResponse:
    rows = order_service.list_orders()
    return OrdersResponse(
        data=[OrderRow.model_validate(row) for row in rows],
        meta=PageMeta(total=len(rows), page=1, per_page=max(len(rows), 1), order_by="placed_at", order="desc"),
    )


@patch(
    "/api/portfolios/{portfolio_id:int}",
    operation_id="updatePortfolio",
    summary="Update portfolio settings",
    description=(
        "Sets the custom display name used throughout the app. Send null or an empty string to go back to the "
        "broker-provided name. reporting_start_date applies from the beginning of that day across reporting, "
        "positions and activity; null restores full history. Omitted fields stay unchanged. Future dates are rejected. "
        "Retains the underlying ledger and original acquisition costs. Returns 404 for an unknown portfolio."
    ),
    responses={
        200: ResponseSpec(data_container=PortfolioCard, description="The updated portfolio."),
        **standard_error_responses(),
    },
    tags=["Investments"],
    sync_to_thread=True,
)
def update_portfolio(portfolio_id: FromPath[int], data: PortfolioUpdate) -> PortfolioCard:
    card = portfolio_service.update_portfolio(portfolio_id, data.model_dump(exclude_unset=True))
    if card is None:
        raise NotFoundException(detail=f"portfolio {portfolio_id} does not exist")
    return PortfolioCard.model_validate(card)


@get(
    "/api/ledger/cash-movements",
    operation_id="listCashMovements",
    summary="List deposits, withdrawals, transfers and conversions",
    description=(
        "External cash flows and internal transfers between the client's currency accounts. The two legs of a "
        "transfer are merged into one row; a cross-currency pair is reported as a conversion with its implied rate."
    ),
    responses={
        200: ResponseSpec(data_container=CashMovementsResponse, description="Cash movements, newest first."),
        **standard_error_responses(),
    },
    tags=["Investments"],
    sync_to_thread=True,
)
def list_cash_movements(kind: FromQuery[str | None] = None) -> CashMovementsResponse:
    rows = queries.list_cash_movements()
    if kind:
        wanted = {value.strip() for value in kind.split(",") if value.strip()}
        rows = [row for row in rows if row["kind"] in wanted]
    return CashMovementsResponse(
        data=[CashMovementRow.model_validate(row) for row in rows],
        meta=PageMeta(total=len(rows), page=1, per_page=max(len(rows), 1), order_by="trade_date", order="desc"),
    )


routes = [
    list_transactions,
    list_positions,
    get_position_detail,
    list_portfolios,
    update_portfolio,
    list_orders,
    list_cash_movements,
]
