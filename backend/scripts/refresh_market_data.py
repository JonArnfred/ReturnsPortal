"""Queue an FX -> prices -> PnL catch-up without blocking local app startup."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from celery import chain

from app.tasks import rebuild_pnl, sync_fx, sync_prices


def main() -> None:
    # Immutable signatures keep each task's report out of the next task's arguments.
    result = chain(sync_fx.si(), sync_prices.si(), rebuild_pnl.si()).apply_async()
    print(f"Market-data refresh queued (FX -> prices -> PnL); final task: {result.id}")


if __name__ == "__main__":
    main()
