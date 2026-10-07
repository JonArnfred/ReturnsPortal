"""UI preferences: saved default filters per page, stored as JSON under a text key."""

from __future__ import annotations

import re
from typing import Any

from app import db
from app.services import preference_sql as sql

KEY_PATTERN = re.compile(r"^[a-z0-9_]+:[a-z0-9_-]+$")


def valid_key(key: str) -> bool:
    """Keys are ``<kind>:<name>``, e.g. ``filters:orders``."""
    return bool(KEY_PATTERN.match(key))


def list_preferences() -> list[dict[str, Any]]:
    return db.select(sql.SELECT_PREFERENCES)


def save_preference(key: str, value: dict[str, Any]) -> dict[str, Any]:
    row = db.select_one(sql.UPSERT_PREFERENCE, {"key": key, "value": db.Jsonb(value)})
    assert row is not None  # RETURNING always yields the row
    return row


def delete_preference(key: str) -> bool:
    return db.execute(sql.DELETE_PREFERENCE, {"key": key}) > 0
