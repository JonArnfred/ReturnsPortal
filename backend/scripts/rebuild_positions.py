"""Rebuild the positions table from the ledger. Usage: rebuild_positions.py [portfolio_id]"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import position_service


def main() -> None:
    report = position_service.rebuild(int(sys.argv[1])) if len(sys.argv) > 1 else position_service.rebuild_all()
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
