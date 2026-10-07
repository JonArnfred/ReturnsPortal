"""Map captured broker payloads into the ledger and reconcile. Usage: ingest_connection.py [connection_id]."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.connection_service as connections
from app.connectors.registry import ingest
from app.services import ledger_service


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ids = [int(sys.argv[1])] if len(sys.argv) > 1 else [c.id for c in connections.list_connections()]
    for connection_id in ids:
        report = ingest(connection_id)
        print(json.dumps(report.as_dict(), indent=2, default=str))
        print("ledger summary:")
        for row in ledger_service.ledger_summary(connection_id):
            span = f"{row['first_date']} .. {row['last_date']}"
            print(f"  {row['kind']:<17} rows={row['rows']:<5} {span}  base={row['amount_base']}")


if __name__ == "__main__":
    main()
