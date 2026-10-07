"""Shared fixtures. ``migrated_db`` gives a test its own PostgreSQL schema in TEST_DATABASE_URL."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pytest import MonkeyPatch

from app import db
from app.services import db_functions

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "db/migrations"
# Every migration, in the order dbmate applies them.
MIGRATIONS = sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql"))


@pytest.fixture
def migrated_db(monkeypatch: MonkeyPatch) -> Iterator[None]:
    """A fresh schema with every migration and the engine's SQL functions; dropped afterwards. Skips the
    test when TEST_DATABASE_URL is not set."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    schema = f"test_{uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            with ConnectionPool(
                url,
                min_size=0,
                max_size=2,
                kwargs={"options": f"-c search_path={schema},public", "row_factory": dict_row},
            ) as pool:
                monkeypatch.setattr(db, "get_pool", lambda: pool)
                for name in MIGRATIONS:
                    db.execute((MIGRATIONS_DIR / name).read_text().split("-- migrate:down")[0])
                db_functions.apply_functions()
                yield
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
