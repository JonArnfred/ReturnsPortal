"""Compare the ledger replay with the latest broker snapshot. Broker-neutral; used by every ingest."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.services import ledger_service as ledger

QUANTITY_TOLERANCE = Decimal("0.000001")
CASH_TOLERANCE = Decimal("0.02")


def reconcile(connection_id: int) -> dict[str, Any]:
    """Quantities per security and cash per account and currency, ledger versus snapshot."""
    positions = ledger.latest_position_snapshot(connection_id)
    if not positions:
        return {"status": "no_snapshot"}
    as_of: date = max(row["snapshot_date"] for row in positions)
    replayed = ledger.ledger_quantities(connection_id, as_of)
    snapshot: dict[int, Decimal] = {}
    symbols: dict[int, str] = {}
    for row in positions:
        snapshot[row["security_id"]] = snapshot.get(row["security_id"], Decimal(0)) + Decimal(row["quantity"])
        symbols[row["security_id"]] = row["symbol"]
    position_issues = []
    for security_id in sorted(set(replayed) | set(snapshot)):
        ledger_quantity = replayed.get(security_id, Decimal(0))
        broker_quantity = snapshot.get(security_id, Decimal(0))
        if abs(ledger_quantity - broker_quantity) > QUANTITY_TOLERANCE:
            position_issues.append(
                {
                    "security_id": security_id,
                    "symbol": symbols.get(security_id),
                    "ledger": str(ledger_quantity),
                    "broker": str(broker_quantity),
                }
            )

    cash_issues = []
    cash_snapshot = ledger.latest_cash_snapshot(connection_id)
    replayed_cash = ledger.ledger_cash(connection_id, as_of)
    for row in cash_snapshot:
        key = (row["account_key"], row["currency"])
        ledger_balance = replayed_cash.get(key, Decimal(0))
        broker_balance = Decimal(row["cash_balance"])
        if abs(ledger_balance - broker_balance) > CASH_TOLERANCE:
            cash_issues.append(
                {
                    "account_key": row["account_key"],
                    "currency": row["currency"],
                    "ledger": str(ledger_balance.quantize(Decimal("0.01"))),
                    "broker": str(broker_balance),
                    "difference": str((ledger_balance - broker_balance).quantize(Decimal("0.01"))),
                }
            )
    return {
        "as_of": as_of.isoformat(),
        "positions_checked": len(set(replayed) | set(snapshot)),
        "position_issues": position_issues,
        "cash_checked": len(cash_snapshot),
        "cash_issues": cash_issues,
        "checked_at": datetime.now(UTC).isoformat(),
    }
