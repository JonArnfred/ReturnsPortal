"""Thin psycopg3 access layer: a shared connection pool plus query helpers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, cast

from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.config import settings

__all__ = [
    "Jsonb",
    "build_upsert",
    "close_pool",
    "execute",
    "get_pool",
    "select",
    "select_one",
    "transaction",
    "upsert_many",
]

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            kwargs={"row_factory": dict_row, "connect_timeout": 5},
            # How long a caller waits for a free connection while others run long queries (a rebuild).
            timeout=10,
            min_size=0,
            max_size=10,
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def transaction() -> Iterator[Connection[Any]]:
    """One connection for several statements, committed together at the end or rolled back on an error.
    Pass it as ``conn`` to ``execute`` and ``upsert_many``."""
    with get_pool().connection() as conn:
        yield conn


@contextmanager
def _connection(conn: Connection[Any] | None) -> Iterator[Connection[Any]]:
    if conn is not None:
        yield conn
    else:
        with get_pool().connection() as pooled:
            yield pooled


def select(sql: str, params: Any = None) -> list[dict[str, Any]]:
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cast(list[dict[str, Any]], cur.fetchall())


def select_one(sql: str, params: Any = None) -> dict[str, Any] | None:
    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cast(dict[str, Any] | None, cur.fetchone())


def execute(sql: str, params: Any = None, *, conn: Connection[Any] | None = None) -> int:
    with _connection(conn) as connection, connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def build_upsert(
    table: str,
    columns: Sequence[str],
    conflict_columns: Sequence[str],
    update_columns: Sequence[str] | None = None,
) -> sql.Composed:
    """Build an INSERT ... ON CONFLICT DO UPDATE statement with %(name)s placeholders.

    Columns not listed in ``update_columns`` (default: every non-conflict column) keep their
    stored value on conflict. An empty update list produces ON CONFLICT DO NOTHING.
    """
    if not columns:
        raise ValueError("upsert needs at least one column")
    if update_columns is None:
        update_columns = [column for column in columns if column not in conflict_columns]
    insert = sql.SQL("INSERT INTO {table} ({columns}) VALUES ({values})").format(
        table=sql.Identifier(table),
        columns=sql.SQL(", ").join(sql.Identifier(column) for column in columns),
        values=sql.SQL(", ").join(sql.Placeholder(column) for column in columns),
    )
    conflict = sql.SQL(" ON CONFLICT ({}) ").format(sql.SQL(", ").join(sql.Identifier(c) for c in conflict_columns))
    if not update_columns:
        return insert + conflict + sql.SQL("DO NOTHING")
    assignments = sql.SQL(", ").join(
        sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(column)) for column in update_columns
    )
    return insert + conflict + sql.SQL("DO UPDATE SET ") + assignments


def upsert_many(
    table: str,
    rows: Sequence[Mapping[str, Any]],
    conflict_columns: Sequence[str],
    update_columns: Sequence[str] | None = None,
    *,
    conn: Connection[Any] | None = None,
) -> int:
    """Insert or update rows in one round trip. All rows must share the same keys."""
    if not rows:
        return 0
    columns = list(rows[0].keys())
    for row in rows[1:]:
        if list(row.keys()) != columns:
            raise ValueError("all rows passed to upsert_many must have the same columns in the same order")
    statement = build_upsert(table, columns, conflict_columns, update_columns)
    with _connection(conn) as connection, connection.cursor() as cur:
        cur.executemany(statement, [dict(row) for row in rows])
        return cur.rowcount
