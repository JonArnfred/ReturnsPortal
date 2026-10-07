"""Rebuild trigger and read models over the PnL engine's derived tables.

The engine itself is SQL (backend/db/functions/100_rebuild_pnl.sql); this module only runs it per
portfolio and serves the results: the paged attribution table, the unitized portfolio series
(per portfolio or all portfolios as one "Total"), and the issues a rebuild recorded.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Context, Decimal
from typing import Any

from psycopg import sql as pg

from app import db
from app.services import pnl_sql as sql
from app.services.ledger_queries import Page

MAX_PER_PAGE = 1000
MIN_DAYS_FOR_ANNUALIZATION = 30


@dataclass(frozen=True)
class PnlFilter:
    portfolio_id: int | None = None
    security_id: int | None = None
    position_kind: str | None = None  # security or cash; anything else means both
    position_type: str | None = None  # long or short
    date_gte: date | None = None
    date_lte: date | None = None
    search: str | None = None
    active_only: bool = True  # skip days where the position is flat and nothing happened


def rebuild(portfolio_id: int, through: date | None = None) -> dict[str, Any]:
    row = db.select_one(sql.REBUILD_PORTFOLIO, {"portfolio_id": portfolio_id, "through": through})
    return {"portfolio_id": portfolio_id, **(row or {})}


def rebuild_all(through: date | None = None) -> dict[str, Any]:
    started = datetime.now(UTC)
    reports = [rebuild(int(row["id"]), through) for row in db.select(sql.SELECT_PORTFOLIO_IDS)]
    return {
        "portfolios": reports,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
    }


def _pnl_where(filters: PnlFilter) -> tuple[pg.Composable, dict[str, Any]]:
    where = sql.PNL_FILTERS
    clauses: list[pg.Composable] = [pg.SQL("TRUE")]
    params: dict[str, Any] = {}
    if filters.portfolio_id is not None:
        clauses.append(pg.SQL(where["portfolio_id"]))
        params["portfolio_id"] = filters.portfolio_id
    if filters.security_id is not None:
        clauses.append(pg.SQL(where["security_id"]))
        params["security_id"] = filters.security_id
    if filters.position_kind in ("security", "cash"):
        clauses.append(pg.SQL(where["position_kind"]))
        params["position_kind"] = filters.position_kind
    if filters.position_type in ("long", "short"):
        clauses.append(pg.SQL(where[filters.position_type]))
    if filters.date_gte is not None:
        clauses.append(pg.SQL(where["date_gte"]))
        params["date_gte"] = filters.date_gte
    if filters.date_lte is not None:
        clauses.append(pg.SQL(where["date_lte"]))
        params["date_lte"] = filters.date_lte
    if filters.search:
        clauses.append(pg.SQL(where["search"]))
        params["search"] = f"%{filters.search.strip()}%"
    if filters.active_only:
        clauses.append(pg.SQL(where["active_only"]))
    return pg.SQL(" AND ").join(clauses), params


def list_pnl_rows(filters: PnlFilter, page: Page) -> tuple[list[dict[str, Any]], int]:
    where, params = _pnl_where(filters)
    order_column = sql.PNL_ORDER_COLUMNS.get(page.order_by, sql.PNL_ORDER_COLUMNS["day"])
    direction = pg.SQL("ASC") if page.order == "asc" else pg.SQL("DESC")
    count_statement = pg.SQL(sql.COUNT_TOTAL) + pg.SQL(sql.PNL_ROWS_BASE) + pg.SQL("WHERE ") + where
    total_row = db.select_one(count_statement.as_string(None), params)
    total = int(total_row["total"]) if total_row else 0
    statement = (
        pg.SQL(sql.PNL_ROWS_COLUMNS)
        + pg.SQL(sql.PNL_ROWS_BASE)
        + pg.SQL("WHERE ")
        + where
        + pg.SQL(sql.PNL_ROWS_PAGE).format(pg.SQL(order_column), direction)
    )
    rows = db.select(
        statement.as_string(None), {**params, "offset": page.offset, "limit": min(page.per_page, MAX_PER_PAGE)}
    )
    return rows, total


def portfolio_days(
    portfolio_id: int | None, date_gte: date | None = None, date_lte: date | None = None
) -> list[dict[str, Any]]:
    """The unitized series of one portfolio, or of all portfolios together when the id is None or 0."""
    params = {"portfolio_id": portfolio_id, "date_gte": date_gte, "date_lte": date_lte}
    if portfolio_id:
        return db.select(sql.SELECT_PORTFOLIO_DAYS, params)
    return db.select(sql.SELECT_TOTAL_DAYS, params)


def series_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Headline figures over a series slice: period return, annualized, max drawdown, last NAV."""
    if not rows:
        return {
            "first_day": None,
            "last_day": None,
            "days": 0,
            "period_return_pct": None,
            "annualized_return_pct": None,
            "max_drawdown_pct": None,
            "nav": None,
            "unit_price": None,
            "cumulative_return_pct": None,
        }
    first, last = rows[0], rows[-1]
    growth = Decimal(1)
    for row in rows:
        growth *= 1 + Decimal(row["daily_return_pct"] or 0)
    period = growth - 1
    first_growth = 1 + Decimal(first["daily_return_pct"] or 0)
    first_unit = Decimal(first["unit_price"]) / first_growth if first_growth else Decimal(100)
    days = (last["day"] - first["day"]).days + 1
    annualized: Decimal | None = None
    if period is not None and days >= MIN_DAYS_FOR_ANNUALIZATION and period > -1:
        annualized = Context(prec=15).plus(((1 + period).ln() * Decimal("365.25") / days).exp() - 1)
    peak = first_unit
    max_dd = Decimal(0)
    for row in rows:
        unit = Decimal(row["unit_price"])
        peak = max(peak, unit)
        if peak > 0:
            max_dd = min(max_dd, unit / peak - 1)
    return {
        "first_day": first["day"],
        "last_day": last["day"],
        "days": days,
        "period_return_pct": period,
        "annualized_return_pct": annualized,
        "max_drawdown_pct": max_dd,
        "nav": last["nav"],
        "unit_price": last["unit_price"],
        "cumulative_return_pct": last["cumulative_return_pct"],
    }


def list_issues() -> list[dict[str, Any]]:
    """Issues newest first; NAV mismatches carry the ECB and broker FX rate per held currency."""
    rates: dict[int, list[dict[str, Any]]] = {}
    for row in db.select(sql.SELECT_ISSUE_FX_RATES):
        rates.setdefault(row.pop("issue_id"), []).append(row)
    return [{**issue, "fx_rates": rates.get(issue["id"], [])} for issue in db.select(sql.SELECT_ISSUES)]


def engine_status() -> list[dict[str, Any]]:
    return db.select(sql.SELECT_ENGINE_STATUS)
