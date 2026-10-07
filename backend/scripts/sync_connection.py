"""Run a broker sync synchronously, without Celery. Usage: sync_connection.py [connection_id] [--full].

``--full`` pulls the whole history again instead of the days since the last successful sync, e.g.
once after a section was added to the IBKR Flex query. For IBKR mind the Flex throttle: a full sync
asks for one statement per year of history, two or more requests each.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.registry import run_sync
from app.services import connection_service as connections


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = [arg for arg in sys.argv[1:] if arg != "--full"]
    full = "--full" in sys.argv[1:]
    if args:
        ids = [int(args[0])]
    else:
        ids = [connection.id for connection in connections.list_connections()]
        if not ids:
            print("No broker connections. Connect a broker in the UI first.", file=sys.stderr)
            sys.exit(1)
    for connection_id in ids:
        print(json.dumps(run_sync(connection_id, full=full).as_dict(), indent=2))


if __name__ == "__main__":
    main()
