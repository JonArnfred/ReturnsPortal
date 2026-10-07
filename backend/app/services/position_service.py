"""Positions: holding episodes of a security in a portfolio.

The episodes themselves live in the ``positions`` table, rebuilt from the ledger by the SQL
function ``rebuild_positions`` (backend/db/functions/200_rebuild_positions.sql) after every ingest;
``position_transactions`` says which ledger rows make up each one. This module runs the rebuild and
serves the read models: the positions list valued at the latest broker mark, and the detail of one
position with its trades and a daily series for charts.

Return = current value + sales - purchases + dividends + costs. ROI divides that by the cash used
to fund the position: purchases plus the costs booked on them. Both are given in the instrument
currency and in the base currency.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Context, Decimal
from typing import Any

from app import db
from app.services import ledger_sql, price_sql
from app.services import position_sql as sql

ZERO = Decimal(0)
PRICE_HISTORY_YEARS = 5


# --- rebuild -------------------------------------------------------------------------------------


def rebuild(portfolio_id: int, security_id: int | None = None) -> dict[str, Any]:
    row = db.select_one(sql.REBUILD, {"portfolio_id": portfolio_id, "security_id": security_id})
    return {"portfolio_id": portfolio_id, **(row or {})}


def rebuild_all() -> dict[str, Any]:
    started = datetime.now(UTC)
    reports = [rebuild(int(row["id"])) for row in db.select(sql.SELECT_PORTFOLIO_IDS)]
    return {"portfolios": reports, "started_at": started.isoformat(), "finished_at": datetime.now(UTC).isoformat()}


# --- valuation -----------------------------------------------------------------------------------


def _annualized(roi: Decimal | None, periods: Decimal, periods_per_year: Decimal) -> Decimal | None:
    if roi is None or periods <= 0:
        return None
    years = periods / periods_per_year
    growth = 1 + roi
    if years < Decimal("0.05") or growth <= 0:
        return None
    try:
        return Context(prec=15).plus((growth.ln() / years).exp() - 1)
    except ArithmeticError:  # decimal.Overflow on absurd growth over a short period
        return None


def _period(row: dict[str, Any], today: date) -> tuple[Decimal, Decimal]:
    end = row["closed"] or today
    days = Decimal((end - max(row["opened"], row.get("reporting_start_date") or row["opened"])).days or 1)
    months = Decimal(max(1, round(int(days) / 30.4375)))
    return days, months


def _engine_is_newer(row: dict[str, Any]) -> bool:
    """True when the engine's latest close postdates the broker mark (a lagging snapshot, e.g. IBKR Flex)."""
    engine_date = row.get("engine_price_date")
    return (
        engine_date is not None
        and row.get("engine_quantity") is not None
        and Decimal(row["engine_quantity"]) == Decimal(row["quantity"])
        and (row["mark_date"] is None or engine_date > row["mark_date"])
    )


def _valuation_date(row: dict[str, Any]) -> date | None:
    valued: date | None = row["engine_price_date"] if _engine_is_newer(row) else row["mark_date"]
    return valued


def _mark_values(row: dict[str, Any]) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """(current price, value in instrument currency, value in base); zeros when closed.

    The broker mark, unless the engine holds a newer close for the same quantity, which then values
    the position as the PnL pages and the price chart do.
    """
    if row["closed"] is not None:
        return None, ZERO, ZERO
    if _engine_is_newer(row):
        return Decimal(row["engine_price"]), Decimal(row["engine_value_local"]), Decimal(row["engine_value_base"])
    price = Decimal(row["current_price"]) if row["current_price"] is not None else None
    quantity = Decimal(row["quantity"])
    value_local = quantity * price if price is not None else None
    if row["mark_value_base"] is not None:
        value_base: Decimal | None = Decimal(row["mark_value_base"])
    elif price is not None and row["fx_rate_base"] is not None:
        value_base = quantity * price * Decimal(row["fx_rate_base"])
    else:
        value_base = None
    return price, value_local, value_base


def _returns_block(
    currency: str,
    *,
    invested: Decimal | None,
    buy_cash: Decimal,
    sell_cash: Decimal,
    value: Decimal | None,
    dividends: Decimal,
    costs: Decimal,
    days: Decimal,
    months: Decimal,
    opening_value: Decimal | None = ZERO,
) -> dict[str, Any]:
    total_return = (
        value - opening_value + sell_cash - buy_cash + dividends + costs
        if value is not None and opening_value is not None
        else None
    )
    roi = total_return / invested if total_return is not None and invested else None
    return {
        "currency": currency,
        "opening_value": opening_value,
        "total_cost": -buy_cash,
        "total_revenue": sell_cash,
        "value": value,
        "dividends": dividends,
        "costs": costs,
        "return_amount": total_return,
        "roi_pct": roi,
        "annualized_days_pct": _annualized(roi, days, Decimal(365)),
        "annualized_months_pct": _annualized(roi, months, Decimal(12)),
    }


def _returns(row: dict[str, Any], side: str, value: Decimal | None, days: Decimal, months: Decimal) -> dict[str, Any]:
    valued = _valuation_date(row)
    if row.get("reporting_start_date") and valued and valued < row["reporting_start_date"]:
        value = None
    currency = (row["currency"] or row["base_currency"]) if side == "local" else row["base_currency"]
    return _returns_block(
        currency,
        invested=row[f"invested_{side}"],
        buy_cash=Decimal(row[f"buy_cash_{side}"]),
        sell_cash=Decimal(row[f"sell_cash_{side}"]),
        value=value,
        dividends=Decimal(row[f"dividends_{side}"]),
        costs=Decimal(row[f"costs_{side}"]),
        days=days,
        months=months,
        opening_value=row.get(f"opening_{side}", ZERO),
    )


def _reporting_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project period activity onto an episode without changing its identity or original costs."""
    start = row.get("reporting_start_date")
    if start is None:
        return row
    result = dict(row)
    for field in ("buys", "sells", "shares_bought", "shares_sold"):
        result[field] = row[f"period_{field}"]
    for side in ("local", "base"):
        opening = row[f"opening_value_{side}"] if row["opened"] < start else ZERO
        result[f"opening_{side}"] = opening
        for field in ("buy_cash", "sell_cash", "dividends", "costs"):
            result[f"{field}_{side}"] = row[f"period_{field}_{side}"]
        result[f"invested_{side}"] = (
            abs(opening) + row[f"period_buy_cash_{side}"] + row[f"period_funding_{side}"]
            if opening is not None
            else None
        )
    return result


def _reporting_notes(row: dict[str, Any]) -> list[str]:
    valued = _valuation_date(row)
    if row.get("reporting_start_date") and valued and valued < row["reporting_start_date"]:
        return ["Latest broker valuation predates the reporting start; period returns are unavailable."]
    if row.get("reporting_start_date") and row.get("opening_base", ZERO) is None:
        return [
            "Opening valuation unavailable; period returns cannot be calculated. "
            "Rebuild reports and check price/FX coverage."
        ]
    return []


def _full_ticker(row: dict[str, Any]) -> str:
    return f"{row['ticker']}:{row['mic']}" if row["mic"] else row["ticker"]


def list_positions(as_of: date | None = None) -> list[dict[str, Any]]:
    """Every position, open ones valued at the broker mark or a newer engine close, with its share of the account."""
    rows = db.select(sql.SELECT_POSITIONS, {"position_id": None})
    aum_by_portfolio = {
        row["portfolio_id"]: Decimal(row["total_value"] or 0) for row in db.select(ledger_sql.SELECT_LATEST_AUM)
    }
    total_aum = sum(aum_by_portfolio.values(), ZERO)
    today = as_of or date.today()

    results: list[dict[str, Any]] = []
    open_value_by_portfolio: dict[int, Decimal] = {}
    for stored_row in rows:
        row = _reporting_row(stored_row)
        is_open = row["closed"] is None
        price, _, value_base = _mark_values(row)
        days, months = _period(row, today)
        base = _returns(row, "base", value_base, days, months)
        notes = _reporting_notes(row)
        if is_open and row["mark_date"] is None:
            notes.append("open in ledger but absent from the broker snapshot")
        if is_open:
            open_value_by_portfolio[row["portfolio_id"]] = open_value_by_portfolio.get(row["portfolio_id"], ZERO) + (
                value_base or ZERO
            )
        results.append(
            {
                "id": row["id"],
                "portfolio_id": row["portfolio_id"],
                "portfolio_name": row["portfolio_name"],
                "security_id": row["security_id"],
                "security_name": row["security_name"],
                "full_ticker": _full_ticker(row),
                "asset_type": row["asset_type"],
                "currency": row["currency"],
                "base_currency": row["base_currency"],
                "position_type": row["position_type"],
                "status": "open" if is_open else "closed",
                "opened": row["opened"],
                "reporting_start_date": row.get("reporting_start_date"),
                "closed": row["closed"],
                "quantity": Decimal(row["quantity"]),
                "trades": row["buys"] + row["sells"],
                "current_price": price,
                "avg_buy_price": row["avg_buy_price"],
                "avg_sell_price": row["avg_sell_price"],
                "value_base": value_base or ZERO,
                "invested_base": row["invested_base"],
                "dividends_base": Decimal(row["dividends_base"]),
                "costs_base": Decimal(row["costs_base"]),
                "return_base": base["return_amount"],
                "roi_pct": base["roi_pct"],
                "annualized_days_pct": base["annualized_days_pct"],
                "annualized_months_pct": base["annualized_months_pct"],
                "pct_aum": ((value_base or ZERO) / total_aum) if total_aum else None,
                "pct_portfolio": None,
                "notes": notes,
            }
        )
    for result in results:
        portfolio_value = open_value_by_portfolio.get(result["portfolio_id"], ZERO)
        result["pct_portfolio"] = (
            (result["value_base"] / portfolio_value) if portfolio_value and result["status"] == "open" else None
        )
    results.sort(key=lambda row: (row["status"] != "open", -abs(row["value_base"]), row["closed"] or today))
    return results


# --- detail --------------------------------------------------------------------------------------


def _merge_corporate_actions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine same-day corporate-action legs (Saxo books a split as sell-all plus buy) into one row."""
    merged: list[dict[str, Any]] = []
    for row in rows:
        previous = merged[-1] if merged else None
        if (
            row["kind"] == "corporate_action"
            and previous is not None
            and previous["kind"] == "corporate_action"
            and previous["trade_date"] == row["trade_date"]
        ):
            previous["quantity"] = Decimal(previous["quantity"] or 0) + Decimal(row["quantity"] or 0)
            continue
        merged.append(dict(row))
    return merged


def position_trades(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trades and corporate actions of a position, oldest first, with prices on the split-adjusted basis.

    ``basis_factor`` on each row (stored by ``rebuild_positions``) brings the booked quantity and price
    onto the basis of the price history, booked and inferred splits alike.
    """
    trades: list[dict[str, Any]] = []
    for row in _merge_corporate_actions(rows):
        if row["kind"] not in ("trade", "corporate_action"):
            continue
        quantity = Decimal(row["quantity"] or 0)
        if row["kind"] == "corporate_action" and quantity == 0:
            continue  # a ticker change books as sell-all plus buy-all; nothing to show
        price = Decimal(row["price"]) if row.get("price") is not None else None
        factor = Decimal(row.get("basis_factor") or 1)
        trades.append(
            {
                "trade_date": row["trade_date"],
                "kind": row["kind"] if row["kind"] == "corporate_action" else ("buy" if quantity > 0 else "sell"),
                "quantity": quantity,
                "price": price,
                "adjusted_price": (price / factor) if price is not None and row["kind"] == "trade" else None,
                "currency": row["currency"],
                "amount_local": Decimal(row["amount_local"] or 0),
                "amount_base": Decimal(row["amount_base"] or 0),
            }
        )
    return trades


def position_series(rows: list[dict[str, Any]], prices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One point per price date from the first trade on: split-adjusted quantity, close, market value.

    Prices are split-adjusted by the source, so the running booked quantity is scaled by the
    ``basis_factor`` of the latest event on or before the day (stored by ``rebuild_positions``);
    a value line then stays continuous through booked and inferred splits.
    """
    events = [row for row in rows if row["kind"] in ("trade", "corporate_action")]
    if not events:
        return []
    series: list[dict[str, Any]] = []
    quantity = ZERO
    factor = Decimal(1)
    index = 0
    for bar in prices:
        day = bar["price_date"]
        if day < events[0]["trade_date"]:
            continue
        while index < len(events) and events[index]["trade_date"] <= day:
            quantity += Decimal(events[index]["quantity"] or 0)
            factor = Decimal(events[index].get("basis_factor") or 1)
            index += 1
        adjusted = quantity * factor
        close = Decimal(bar["close"])
        series.append({"date": day, "quantity": adjusted, "close": close, "market_value": adjusted * close})
    return series


def position_detail(position_id: int, as_of: date | None = None) -> dict[str, Any] | None:
    """Everything the position page shows, or None for an unknown id."""
    row = db.select_one(sql.SELECT_POSITIONS, {"position_id": position_id})
    if row is None:
        return None
    original_cost_local = -row["buy_cash_local"]
    original_cost_base = -row["buy_cash_base"]
    row = _reporting_row(row)
    start = row.get("reporting_start_date")
    today = as_of or date.today()
    is_open = row["closed"] is None
    price, value_local, value_base = _mark_values(row)
    days, months = _period(row, today)
    transactions = db.select(sql.SELECT_POSITION_TRANSACTIONS, {"position_id": position_id})
    # Price context for the chart's 1Y and 5Y ranges reaches back five years from today (or to the
    # opening date, if earlier) and runs to today; the holding series itself stops at the closing date.
    history_start = min(row["opened"], today.replace(year=today.year - PRICE_HISTORY_YEARS))
    history = db.select(
        price_sql.SELECT_DAILY_PRICES, {"security_id": row["security_id"], "date_gte": history_start, "date_lte": None}
    )
    end = row["closed"] or today
    prices = [bar for bar in history if row["opened"] <= bar["price_date"] <= end]
    notes = ["open in ledger but absent from the broker snapshot"] if is_open and row["mark_date"] is None else []
    notes.extend(_reporting_notes(row))
    return {
        "reporting_start_date": start,
        "original_cost_local": original_cost_local,
        "original_cost_base": original_cost_base,
        "id": row["id"],
        "portfolio_id": row["portfolio_id"],
        "portfolio_name": row["portfolio_name"],
        "security_id": row["security_id"],
        "security_name": row["security_name"],
        "full_ticker": _full_ticker(row),
        "asset_type": row["asset_type"],
        "currency": row["currency"],
        "base_currency": row["base_currency"],
        "position_type": row["position_type"],
        "status": "open" if is_open else "closed",
        "opened": row["opened"],
        "closed": row["closed"],
        "current_price": price,
        "price_date": _valuation_date(row),
        "shares": {
            "buys": row["buys"],
            "shares_bought": Decimal(row["shares_bought"]),
            "sells": row["sells"],
            "shares_sold": Decimal(row["shares_sold"]),
            "current": Decimal(row["quantity"]),
        },
        "returns_local": _returns(row, "local", value_local, days, months),
        "returns_base": _returns(row, "base", value_base, days, months),
        "trades": position_trades([t for t in transactions if start is None or t["trade_date"] >= start]),
        "series": [point for point in position_series(transactions, prices) if start is None or point["date"] >= start],
        "price_history": [{"date": bar["price_date"], "close": Decimal(bar["close"])} for bar in history],
        "notes": notes,
    }
