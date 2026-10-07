"""Fetch ECB reference rates and rebuild the crossed FX table. Usage: sync_fx.py"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import fx_service


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(json.dumps(fx_service.sync_fx().as_dict(), indent=2))


if __name__ == "__main__":
    main()
