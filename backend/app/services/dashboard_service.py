"""A consistent dashboard snapshot; all money stays Decimal until presentation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from psycopg.rows import dict_row

from app import db
from app.services import dashboard_sql as sql
from app.services import pnl_sql


def dashboard() -> dict[str, Any]:
    # A rebuild can replace the derived rows while this request is running. Read all sections
    # from the same committed snapshot, without blocking the rebuild or triggering any writes.
    with db.get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SNAPSHOT)
        cur.execute(sql.COVERAGE)
        coverage = cur.fetchall()
        warnings = []
        for row in coverage:
            if row["last_day"] is None:
                warnings.append(f"{row['portfolio_name']} has no calculated returns and is excluded from totals.")
        available = [row for row in coverage if row["last_day"] is not None]
        result: dict[str, Any] = {
            "as_of": None,
            "intraday": False,
            "base_currency": None,
            "nav": None,
            "daily_pnl": None,
            "daily_return_pct": None,
            "fx_effect_base": None,
            "issue_count": sum(row["issues"] for row in coverage),
            "series": [],
            "portfolios": [
                {**row, "nav": None, "daily_pnl": None, "daily_return_pct": None, "cumulative_return_pct": None}
                for row in coverage
            ],
            "fx_by_currency": [],
            "top": [],
            "bottom": [],
            "warnings": warnings,
        }
        if not available:
            return result
        if len({row["base_currency"] for row in available}) != 1:
            warnings.append("Combined totals are unavailable because portfolios use different base currencies.")
            return result
        last_shared_day = min(row["last_day"] for row in available)
        if any(row["first_day"] > last_shared_day for row in available):
            warnings.append("Combined totals are unavailable: portfolios have no shared reporting date.")
            return result
        cur.execute(sql.VALUATION_DAY, {"day": last_shared_day, "portfolio_count": len(available)})
        valuation = cur.fetchone()
        if valuation is None:
            warnings.append("No completed valuation date is available; daily results are pending.")
            return result
        day = valuation["day"]
        if day < last_shared_day:
            warnings.append(
                f"Daily results after {day} are pending: later dates only carry forward earlier market data. "
                "NAV, daily results and contributors use the date shown."
            )
        params = {"day": day}
        cur.execute(sql.PORTFOLIOS, params)
        portfolio_rows = {row["portfolio_id"]: row for row in cur.fetchall()}
        if len(portfolio_rows) != len(available):
            warnings.append("Combined totals are unavailable: portfolios have no shared reporting date.")
            return result
        if any(row["last_day"] != last_shared_day for row in available):
            warnings.append(f"Totals use {day}, the latest shared reporting date; some portfolios have newer data.")
        result["as_of"] = day
        result["intraday"] = valuation["intraday"]
        result["base_currency"] = available[0]["base_currency"]
        result["portfolios"] = [{**row, **portfolio_rows.get(row["portfolio_id"], {})} for row in result["portfolios"]]
        cur.execute(sql.TOTAL, params)
        result.update(cur.fetchone() or {})
        cur.execute(sql.SERIES, params)
        result["series"] = cur.fetchall()
        cur.execute(sql.FX, params)
        fx = cur.fetchall()
        result["fx_effect_base"] = sum((row["effect"] for row in fx), Decimal(0))
        result["fx_by_currency"] = [row for row in fx if row["currency"] != result["base_currency"]]
        for key, direction in (("top", "DESC"), ("bottom", "ASC")):
            cur.execute(
                pnl_sql.PNL_ROWS_COLUMNS + pnl_sql.PNL_ROWS_BASE + sql.CONTRIBUTORS.format(direction=direction), params
            )
            result[key] = cur.fetchall()
        return result
