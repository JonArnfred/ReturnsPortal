"""Read models over the ledger for the UI: paged transactions, latest positions, cash movements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import sql as pg

from app import db
from app.services import ledger_sql as sql

TRANSACTION_KINDS = {
    "trade",
    "corporate_action",
    "deposit",
    "withdrawal",
    "transfer",
    "dividend",
    "withholding_tax",
    "commission",
    "fee",
    "tax",
    "interest",
    "lending_income",
    "other",
}
MAX_PER_PAGE = 1000


@dataclass(frozen=True)
class TransactionFilter:
    kinds: tuple[str, ...] = ()
    portfolio_id: int | None = None
    account: int | None = None  # broker_accounts.id
    trade_type: str | None = None  # buy, sell or corporate_action
    date_gte: date | None = None
    date_lte: date | None = None
    search: str | None = None


@dataclass(frozen=True)
class Page:
    page: int
    per_page: int
    order_by: str
    order: str

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


def account_label(account_id: str | None, currency: str | None) -> str | None:
    if not account_id and not currency:
        return None
    return f"{account_id or '?'} ({currency})" if currency else account_id


def _transaction_where(filters: TransactionFilter) -> tuple[pg.Composable, dict[str, Any]]:
    where = sql.TRANSACTION_FILTERS
    clauses: list[pg.Composable] = [pg.SQL(where["reporting_start"])]
    params: dict[str, Any] = {}
    kinds = [kind for kind in filters.kinds if kind in TRANSACTION_KINDS]
    if kinds:
        clauses.append(pg.SQL(where["kinds"]))
        params["kinds"] = kinds
    if filters.portfolio_id is not None:
        clauses.append(pg.SQL(where["portfolio_id"]))
        params["portfolio_id"] = filters.portfolio_id
    if filters.account is not None:
        clauses.append(pg.SQL(where["account"]))
        params["account"] = filters.account
    if filters.trade_type in sql.TRANSACTION_TRADE_TYPES:
        clauses.append(pg.SQL(sql.TRANSACTION_TRADE_TYPES[filters.trade_type]))
    if filters.date_gte is not None:
        clauses.append(pg.SQL(where["date_gte"]))
        params["date_gte"] = filters.date_gte
    if filters.date_lte is not None:
        clauses.append(pg.SQL(where["date_lte"]))
        params["date_lte"] = filters.date_lte
    if filters.search:
        clauses.append(pg.SQL(where["search"]))
        params["search"] = f"%{filters.search.strip()}%"
    return pg.SQL(" AND ").join(clauses), params


def list_transactions(filters: TransactionFilter, page: Page) -> tuple[list[dict[str, Any]], int]:
    where, params = _transaction_where(filters)
    order_column = sql.TRANSACTION_ORDER_COLUMNS.get(page.order_by, sql.TRANSACTION_ORDER_COLUMNS["trade_date"])
    direction = pg.SQL("ASC") if page.order == "asc" else pg.SQL("DESC")
    count_statement = pg.SQL(sql.COUNT_TOTAL) + pg.SQL(sql.SELECT_TRANSACTIONS_BASE) + pg.SQL("WHERE ") + where
    total_row = db.select_one(count_statement.as_string(None), params)
    total = int(total_row["total"]) if total_row else 0
    statement = (
        pg.SQL(sql.SELECT_TRANSACTIONS_COLUMNS)
        + pg.SQL(sql.SELECT_TRANSACTIONS_BASE)
        + pg.SQL("WHERE ")
        + where
        + pg.SQL(sql.TRANSACTIONS_PAGE).format(pg.SQL(order_column), direction)
    )
    rows = db.select(
        statement.as_string(None), {**params, "offset": page.offset, "limit": min(page.per_page, MAX_PER_PAGE)}
    )
    for row in rows:
        row["account_label"] = account_label(row.pop("account_id"), row.pop("account_label_currency"))
        row["full_ticker"] = (
            f"{row['ticker']}:{row['mic']}" if row.get("ticker") and row.get("mic") else row.get("ticker")
        )
    return rows, total


def list_positions() -> list[dict[str, Any]]:
    rows = db.select(sql.SELECT_LATEST_POSITIONS)
    for row in rows:
        row["account_label"] = account_label(row.pop("account_id"), row.pop("account_label_currency"))
        row["full_ticker"] = f"{row['ticker']}:{row['mic']}" if row.get("mic") else row["ticker"]
        row["position_type"] = "short" if Decimal(row["quantity"]) < 0 else "long"
    rows.sort(key=lambda row: Decimal(row["market_value_base"] or 0), reverse=True)
    return rows


def pair_cash_movements(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the two legs of an internal transfer into one row; label cross-currency pairs as conversions.

    Legs share ``related_ref``. A leg without a partner is shown on its own.
    """
    by_ref: dict[str, list[dict[str, Any]]] = {}
    singles: list[dict[str, Any]] = []
    for row in rows:
        ref = row.get("related_ref")
        if row["kind"] == "transfer" and ref:
            by_ref.setdefault(ref, []).append(row)
        else:
            singles.append(row)

    def movement(
        kind: str, source: dict[str, Any] | None, target: dict[str, Any] | None, anchor: dict[str, Any]
    ) -> dict[str, Any]:
        from_amount = Decimal(source["amount_local"]) if source else None
        to_amount = Decimal(target["amount_local"]) if target else None
        rate = None
        if kind == "conversion" and from_amount and to_amount:
            rate = (to_amount / abs(from_amount)).quantize(Decimal("0.000001"))
        return {
            "id": anchor["id"],
            "trade_date": anchor["trade_date"],
            "value_date": anchor["value_date"],
            "kind": kind,
            "portfolio_name": anchor["portfolio_name"],
            "from_account": account_label(source["account_id"], source["account_label_currency"]) if source else None,
            "from_currency": source["currency"] if source else None,
            "from_amount": from_amount,
            "to_account": account_label(target["account_id"], target["account_label_currency"]) if target else None,
            "to_currency": target["currency"] if target else None,
            "to_amount": to_amount,
            "rate": rate,
            "base_currency": anchor["base_currency"],
            "amount_base": Decimal(anchor["amount_base"]) if anchor["amount_base"] is not None else None,
            "description": anchor["description"],
        }

    result: list[dict[str, Any]] = []
    for row in singles:
        if row["kind"] == "deposit":
            result.append(movement("deposit", None, row, row))
        elif row["kind"] == "withdrawal":
            result.append(movement("withdrawal", row, None, row))
        else:
            result.append(
                movement(
                    "transfer",
                    row if Decimal(row["amount_local"]) < 0 else None,
                    row if Decimal(row["amount_local"]) >= 0 else None,
                    row,
                )
            )
    for legs in by_ref.values():
        outgoing = [leg for leg in legs if Decimal(leg["amount_local"]) < 0]
        incoming = [leg for leg in legs if Decimal(leg["amount_local"]) >= 0]
        if len(outgoing) == 1 and len(incoming) == 1:
            source, target = outgoing[0], incoming[0]
            kind = "conversion" if source["currency"] != target["currency"] else "transfer"
            anchor = target
            result.append(
                movement(kind, source, target, {**anchor, "amount_base": abs(Decimal(target["amount_base"] or 0))})
            )
        else:
            for leg in legs:
                is_out = Decimal(leg["amount_local"]) < 0
                result.append(movement("transfer", leg if is_out else None, None if is_out else leg, leg))
    result.sort(key=lambda row: (row["trade_date"], row["id"]), reverse=True)
    return result


def list_cash_movements() -> list[dict[str, Any]]:
    return pair_cash_movements(db.select(sql.SELECT_CASH_MOVEMENTS))
