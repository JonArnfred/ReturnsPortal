"""Export the public OpenAPI document used by generated clients and CI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.api import app


def main() -> None:
    destination = Path(__file__).resolve().parents[2] / "openapi" / "openapi.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(app.openapi_schema.to_schema(), indent=2) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
