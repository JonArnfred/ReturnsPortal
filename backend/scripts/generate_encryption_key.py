"""Print a fresh Fernet key for SECRETS_ENCRYPTION_KEY."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.secrets import generate_key

if __name__ == "__main__":
    print(generate_key())
