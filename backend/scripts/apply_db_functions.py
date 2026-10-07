"""Apply backend/db/functions/*.sql to the configured database. Run after dbmate migrations."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import db_functions


def main() -> None:
    for name in db_functions.apply_functions():
        print(f"applied {name}")


if __name__ == "__main__":
    main()
