from __future__ import annotations

import pytest

from app import db


def test_build_upsert_updates_non_conflict_columns() -> None:
    statement = db.build_upsert(
        "broker_accounts", ["connection_id", "account_key", "currency"], ["connection_id", "account_key"]
    )
    text = statement.as_string(None)
    assert text.startswith('INSERT INTO "broker_accounts" ("connection_id", "account_key", "currency")')
    assert "VALUES (%(connection_id)s, %(account_key)s, %(currency)s)" in text
    assert 'ON CONFLICT ("connection_id", "account_key") DO UPDATE SET "currency" = EXCLUDED."currency"' in text


def test_build_upsert_do_nothing_when_nothing_to_update() -> None:
    statement = db.build_upsert("t", ["a"], ["a"])
    assert statement.as_string(None).endswith('ON CONFLICT ("a") DO NOTHING')


def test_build_upsert_rejects_empty_columns() -> None:
    with pytest.raises(ValueError):
        db.build_upsert("t", [], ["a"])


def test_upsert_many_requires_uniform_rows() -> None:
    with pytest.raises(ValueError):
        db.upsert_many("t", [{"a": 1}, {"b": 2}], ["a"])
    assert db.upsert_many("t", [], ["a"]) == 0
