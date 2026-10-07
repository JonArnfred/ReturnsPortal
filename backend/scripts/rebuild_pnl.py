"""Rebuild the derived PnL tables synchronously. Usage: rebuild_pnl.py [portfolio_id] [through YYYY-MM-DD]"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import pnl_service


def main() -> None:
    args = sys.argv[1:]
    through = date.fromisoformat(args[1]) if len(args) > 1 else None
    report = pnl_service.rebuild(int(args[0]), through) if args else pnl_service.rebuild_all(through)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
