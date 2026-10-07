"""Create or replace the IBKR connection from IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in backend/.env.

Usage: connect_ibkr.py [token-expiry YYYY-MM-DD] [--sync]

Without an expiry the token is assumed to last a year. With ``--sync`` the statement pull and ingest
run right away, synchronously; otherwise queue a refresh from the Connections page or run
``sync_connection.py`` and ``ingest_connection.py``.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.connectors.ibkr import connect


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not settings.ibkr_flex_token or not settings.ibkr_flex_query_id:
        print("Set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in backend/.env first.", file=sys.stderr)
        sys.exit(1)
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    expires_at = datetime.combine(datetime.fromisoformat(args[0]).date(), time.max, tzinfo=UTC) if args else None
    connection_id = connect.connect(settings.ibkr_flex_token, settings.ibkr_flex_query_id, expires_at)
    print(f"IBKR connection stored as connection {connection_id}")
    if "--sync" in sys.argv:
        from app.connectors.ibkr import ingest, sync

        print(json.dumps(sync.run_sync(connection_id).as_dict(), indent=2))
        print(json.dumps(ingest.ingest(connection_id).as_dict(), indent=2, default=str))


if __name__ == "__main__":
    main()
