"""Fetch daily prices synchronously. Usage: sync_prices.py [connection_id] [security_id ...]."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import connection_service as connections
from app.services import price_service


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = [int(value) for value in sys.argv[1:]]
    ids = [args[0]] if args else [connection.id for connection in connections.list_connections()]
    only = set(args[1:]) or None
    for connection_id in ids:
        print(json.dumps(price_service.sync_prices(connection_id, security_ids=only).as_dict(), indent=2))


if __name__ == "__main__":
    main()
