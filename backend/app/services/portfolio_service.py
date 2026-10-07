"""Portfolio cards: one summary per portfolio from the latest broker snapshot and the open positions."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app import db
from app.services import ledger_sql as sql
from app.services import position_service

ZERO = Decimal(0)


def summarize(
    portfolios: list[dict[str, Any]],
    aum_rows: list[dict[str, Any]],
    cash_rows: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    accounts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Pure aggregation: broker cash and total per portfolio, open positions counted and valued from the ledger."""
    aum = {row["portfolio_id"]: row for row in aum_rows}
    accounts_by_portfolio: dict[int, list[dict[str, Any]]] = {}
    for row in accounts or []:
        label = (
            f"{row['account_id']} ({row['currency']})" if row["account_id"] and row["currency"] else row["account_id"]
        )
        accounts_by_portfolio.setdefault(row["portfolio_id"], []).append(
            {
                "id": row["id"],
                "account_id": row["account_id"],
                "currency": row["currency"],
                "label": label or str(row["id"]),
                "active": bool(row["active"]),
            }
        )
    cash_by_portfolio: dict[int, list[dict[str, Any]]] = {}
    for row in cash_rows:
        cash_by_portfolio.setdefault(row["portfolio_id"], []).append(
            {"currency": row["currency"], "amount": Decimal(row["cash_balance"])}
        )
    open_count: dict[int, int] = {}
    open_value: dict[int, Decimal] = {}
    for position in positions:
        if position["status"] != "open":
            continue
        pid = position["portfolio_id"]
        open_count[pid] = open_count.get(pid, 0) + 1
        open_value[pid] = open_value.get(pid, ZERO) + Decimal(position["value_base"])

    cards: list[dict[str, Any]] = []
    for portfolio in portfolios:
        pid = portfolio["id"]
        snapshot = aum.get(pid)
        cash = Decimal(snapshot["cash_balance"]) if snapshot and snapshot["cash_balance"] is not None else None
        total = Decimal(snapshot["total_value"]) if snapshot and snapshot["total_value"] is not None else None
        positions_value = open_value.get(pid, ZERO)
        unbooked = Decimal(snapshot["unbooked"]) if snapshot and snapshot.get("unbooked") is not None else None
        unexplained = (
            (total - cash - positions_value - (unbooked or ZERO)) if total is not None and cash is not None else None
        )
        cards.append(
            {
                "id": pid,
                "name": portfolio["name"],
                "broker_name": portfolio.get("broker_name", portfolio["name"]),
                "display_name": portfolio.get("display_name"),
                "reporting_start_date": portfolio.get("reporting_start_date"),
                "base_currency": portfolio["base_currency"],
                "broker": portfolio.get("broker"),
                "environment": portfolio.get("environment"),
                "connection_status": portfolio.get("connection_status"),
                "last_sync_finished_at": portfolio.get("last_sync_finished_at"),
                "snapshot_date": snapshot["snapshot_date"] if snapshot else None,
                "open_positions": open_count.get(pid, 0),
                "positions_value_base": positions_value,
                "cash_base": cash,
                "total_value_base": total,
                "unbooked_base": unbooked,
                "unexplained_base": unexplained,
                "cash_by_currency": cash_by_portfolio.get(pid, []),
                "accounts": accounts_by_portfolio.get(pid, []),
            }
        )
    return cards


def list_portfolios() -> list[dict[str, Any]]:
    return summarize(
        db.select(sql.SELECT_PORTFOLIOS),
        db.select(sql.SELECT_LATEST_AUM),
        db.select(sql.SELECT_LATEST_CASH_BY_CURRENCY),
        position_service.list_positions(),
        db.select(sql.SELECT_PORTFOLIO_ACCOUNTS),
    )


def normalize_display_name(value: str | None) -> str | None:
    """Trim whitespace; an empty name means "use the broker name"."""
    cleaned = " ".join((value or "").split())
    return cleaned or None


def update_portfolio(portfolio_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
    """Only supplied fields change; explicit null restores the corresponding default."""
    updated = db.execute(
        sql.UPDATE_PORTFOLIO,
        {
            "portfolio_id": portfolio_id,
            "set_name": "display_name" in changes,
            "display_name": normalize_display_name(changes.get("display_name")),
            "set_start": "reporting_start_date" in changes,
            "reporting_start_date": changes.get("reporting_start_date"),
        },
    )
    if not updated:
        return None
    return next((card for card in list_portfolios() if card["id"] == portfolio_id), None)
