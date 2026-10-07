"""Apply the SQL functions in backend/db/functions in file order (idempotent CREATE OR REPLACE)."""

from __future__ import annotations

from pathlib import Path

from app import db

FUNCTIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "functions"


def function_files() -> list[Path]:
    return sorted(FUNCTIONS_DIR.glob("*.sql"))


def apply_functions() -> list[str]:
    """Run every function file against the configured database; returns the file names applied."""
    applied: list[str] = []
    for path in function_files():
        db.execute(path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return applied
