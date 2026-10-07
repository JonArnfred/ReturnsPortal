"""Real PostgreSQL checks for broker connection storage; needs TEST_DATABASE_URL."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pytest import MonkeyPatch

from app import db
from app.config import settings
from app.connectors.saxo.auth import TokenSet
from app.services import connection_service as connections
from app.services import secrets


def account(key: str, currency: str | None) -> connections.BrokerAccount:
    return connections.BrokerAccount(
        account_key=key, account_id=None, currency=currency, account_type=None, active=True, raw={"AccountKey": key}
    )


@pytest.fixture
def connections_db(migrated_db: None, monkeypatch: MonkeyPatch) -> Iterator[None]:
    secrets._fernet.cache_clear()
    monkeypatch.setattr(settings, "secrets_encryption_key", secrets.generate_key())
    yield
    secrets._fernet.cache_clear()


def test_oauth_state_is_single_use(connections_db: None) -> None:
    state = connections.create_oauth_state("saxo")
    assert connections.consume_oauth_state(state) is not None
    assert connections.consume_oauth_state(state) is None
    assert connections.consume_oauth_state("unknown") is None


def test_connection_roundtrip(connections_db: None) -> None:
    tokens = TokenSet(access_token="acc-1", expires_in=1200, refresh_token="ref-1", refresh_token_expires_in=3600)
    connection_id = connections.save_connection("saxo", "live", tokens)
    assert connections.save_connection("saxo", "live", tokens) == connection_id  # one row per broker/environment

    loaded = connections.load_secrets(connection_id)
    assert loaded is not None and loaded.access_token == "acc-1" and loaded.refresh_token == "ref-1"
    stored = db.select_one("SELECT access_token_encrypted FROM broker_connections WHERE id = %s", (connection_id,))
    assert stored is not None and "acc-1" not in stored["access_token_encrypted"]

    connections.store_tokens(connection_id, TokenSet(access_token="acc-2", expires_in=60))
    reloaded = connections.load_secrets(connection_id)
    assert reloaded is not None and reloaded.access_token == "acc-2" and reloaded.refresh_token == "ref-1"

    connections.update_client_details(connection_id, client_key="CK", client_name="Tester", base_currency="DKK")
    assert connections.upsert_account_records(connection_id, [account("A", "DKK"), account("B", None)]) == 2
    assert connections.upsert_account_records(connection_id, [account("A", "EUR")]) == 1
    connections.mark_sync_started(connection_id)
    connections.record_raw_payload(connection_id, "port/v1/positions", {"ClientKey": "CK"}, 200, {"Data": []})
    connections.mark_sync_finished(connection_id, error=None)

    [status] = connections.list_connections()
    assert status.id == connection_id and status.client_key == "CK" and status.base_currency == "DKK"
    assert status.account_count == 2 and status.status == "connected" and status.last_sync_finished_at is not None
    row = db.select_one("SELECT currency FROM broker_accounts WHERE account_key = 'A'")
    assert row is not None and row["currency"] == "EUR"
    payload = db.select_one("SELECT endpoint, status_code, payload FROM broker_raw_payloads")
    assert payload == {"endpoint": "port/v1/positions", "status_code": 200, "payload": {"Data": []}}

    connections.mark_sync_finished(connection_id, error="boom")
    [status] = connections.list_connections()
    assert status.status == "error" and status.last_sync_error == "boom"
    assert status.last_success_finished_at is not None

    connections.mark_token_expired(connection_id, "token rejected")
    connections.mark_sync_finished(connection_id, error="token rejected")
    [status] = connections.list_connections()
    assert status.status == "expired"  # stays expired until the broker is authorized again


def test_latest_snapshots_come_from_the_last_successful_sync(connections_db: None) -> None:
    connection_id = connections.save_connection("saxo", "live", TokenSet(access_token="acc", expires_in=1200))

    def latest() -> list[object]:
        return [p.payload for p in connections.raw_payloads(connection_id, "port/v1/positions", latest_run_only=True)]

    connections.mark_sync_started(connection_id)
    connections.record_raw_payload(connection_id, "port/v1/positions", {}, 200, {"Data": ["first"]})
    assert latest() == [{"Data": ["first"]}]  # before any run has finished: the most recent run
    connections.mark_sync_finished(connection_id, error=None)

    connections.mark_sync_started(connection_id)
    connections.record_raw_payload(connection_id, "port/v1/positions", {}, 200, {"Data": ["partial"]})
    connections.mark_sync_finished(connection_id, error="HTTP 503")
    assert latest() == [{"Data": ["first"]}]

    connections.mark_sync_started(connection_id)
    connections.record_raw_payload(connection_id, "port/v1/positions", {}, 200, {"Data": ["third"]})
    connections.mark_sync_finished(connection_id, error=None)
    assert latest() == [{"Data": ["third"]}]
    every = connections.raw_payloads(connection_id, "port/v1/positions", latest_run_only=False)
    assert len(every) == 3
