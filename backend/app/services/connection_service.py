"""Broker connections: OAuth state, encrypted token storage, accounts, and raw payload capture."""

from __future__ import annotations

import secrets as token_secrets
from collections.abc import Collection
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app import db
from app.services import connection_sql as sql
from app.services import secrets


class TokenLike(Protocol):
    """What a broker's credential object must expose to be stored: Saxo's ``TokenSet`` and IBKR's
    ``FlexCredentials`` both fit. A broker without refresh tokens leaves those None."""

    @property
    def access_token(self) -> str: ...

    @property
    def refresh_token(self) -> str | None: ...

    @property
    def access_token_expires_at(self) -> datetime: ...

    @property
    def refresh_token_expires_at(self) -> datetime | None: ...


class ConnectionSecrets(BaseModel):
    """Decrypted tokens for a connection. Never returned by the API."""

    id: int
    broker: str
    environment: str
    client_key: str | None
    access_token: str
    refresh_token: str | None
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime | None
    query_id: str | None = None


class ConnectionStatus(BaseModel):
    """Public view of a broker connection, without any token material."""

    id: int = Field(description="Connection identifier.", examples=[1])
    broker: str = Field(description="Broker key.", examples=["saxo"])
    environment: str = Field(description="Broker environment, live or sim.", examples=["live"])
    client_key: str | None = Field(description="Broker-side client key once the first sync ran.")
    client_name: str | None = Field(description="Client name reported by the broker.")
    base_currency: str | None = Field(description="Client default currency reported by the broker.", examples=["EUR"])
    status: str = Field(description="connected, expired, or error.", examples=["connected"])
    query_id: str | None = Field(default=None, description="Report query id for brokers that pull reports (IBKR Flex).")
    account_count: int = Field(description="Active broker accounts found by the last sync.", examples=[2])
    access_token_expires_at: datetime = Field(description="When the current access token expires.")
    refresh_token_expires_at: datetime | None = Field(description="When the refresh token expires, if known.")
    last_sync_started_at: datetime | None = Field(description="Start of the most recent sync.")
    last_sync_finished_at: datetime | None = Field(description="End of the most recent sync.")
    last_sync_error: str | None = Field(description="Error message of the most recent sync, if it failed.")
    last_success_finished_at: datetime | None = Field(description="End of the most recent successful sync.")
    created_at: datetime = Field(description="When the connection was first authorized.")


class BrokerAccount(BaseModel):
    account_key: str
    account_id: str | None
    currency: str | None
    account_type: str | None
    active: bool
    raw: dict[str, Any]


def create_oauth_state(broker: str) -> str:
    state = token_secrets.token_urlsafe(32)
    db.execute(sql.INSERT_OAUTH_STATE, {"state": state, "broker": broker})
    db.execute(sql.PURGE_OAUTH_STATES)
    return state


def consume_oauth_state(state: str) -> dict[str, Any] | None:
    """Delete and return the state row if it exists and is fresh; None otherwise."""
    return db.select_one(sql.CONSUME_OAUTH_STATE, {"state": state})


def save_connection(broker: str, environment: str, tokens: TokenLike, *, query_id: str | None = None) -> int:
    row = db.select_one(
        sql.UPSERT_CONNECTION,
        {
            "broker": broker,
            "environment": environment,
            "access_token_encrypted": secrets.encrypt(tokens.access_token),
            "refresh_token_encrypted": secrets.encrypt(tokens.refresh_token) if tokens.refresh_token else None,
            "access_token_expires_at": tokens.access_token_expires_at,
            "refresh_token_expires_at": tokens.refresh_token_expires_at,
            "query_id": query_id,
        },
    )
    assert row is not None
    return int(row["id"])


def store_tokens(connection_id: int, tokens: TokenLike) -> None:
    db.execute(
        sql.STORE_TOKENS,
        {
            "id": connection_id,
            "access_token_encrypted": secrets.encrypt(tokens.access_token),
            "refresh_token_encrypted": secrets.encrypt(tokens.refresh_token) if tokens.refresh_token else None,
            "access_token_expires_at": tokens.access_token_expires_at,
            "refresh_token_expires_at": tokens.refresh_token_expires_at,
        },
    )


def load_secrets(connection_id: int) -> ConnectionSecrets | None:
    row = db.select_one(sql.SELECT_CONNECTION_SECRETS, {"id": connection_id})
    if row is None:
        return None
    return ConnectionSecrets(
        id=row["id"],
        broker=row["broker"],
        environment=row["environment"],
        client_key=row["client_key"],
        access_token=secrets.decrypt(row["access_token_encrypted"]),
        refresh_token=secrets.decrypt(row["refresh_token_encrypted"]) if row["refresh_token_encrypted"] else None,
        access_token_expires_at=row["access_token_expires_at"],
        refresh_token_expires_at=row["refresh_token_expires_at"],
        query_id=row["query_id"],
    )


def list_connections() -> list[ConnectionStatus]:
    return [ConnectionStatus.model_validate(row) for row in db.select(sql.SELECT_CONNECTIONS)]


class ClientMismatchError(RuntimeError):
    """The broker login belongs to a different client than the one this connection already holds."""


def ensure_same_client(connection: ConnectionSecrets, client_keys: Collection[str]) -> None:
    """Refuse to capture another client's data into this connection's portfolio.

    There is one connection per broker and environment, so authorizing a second client of the same
    broker would otherwise mix both clients' history into one portfolio. Call it before storing
    anything from the broker.
    """
    keys = {key for key in client_keys if key}
    if connection.client_key and keys and connection.client_key not in keys:
        raise ClientMismatchError(
            f"this {connection.broker} connection belongs to client {connection.client_key}, but the broker"
            f" login is for {', '.join(sorted(keys))}; one client per broker is supported, so reconnect with"
            " the original client's credentials"
        )


def update_client_details(
    connection_id: int, *, client_key: str, client_name: str | None, base_currency: str | None
) -> None:
    db.execute(
        sql.UPDATE_CLIENT_DETAILS,
        {"id": connection_id, "client_key": client_key, "client_name": client_name, "base_currency": base_currency},
    )


def mark_sync_started(connection_id: int) -> None:
    db.execute(sql.MARK_SYNC_STARTED, {"id": connection_id})


def mark_token_expired(connection_id: int, error: str) -> None:
    """The refresh token no longer works; the user has to authorize the broker again."""
    db.execute(sql.MARK_TOKEN_EXPIRED, {"id": connection_id, "error": error[:1000]})


def mark_sync_finished(connection_id: int, error: str | None) -> None:
    db.execute(sql.MARK_SYNC_FINISHED, {"id": connection_id, "error": error})


def upsert_account_records(connection_id: int, accounts: list[BrokerAccount]) -> int:
    """Account storage; connectors map their own payloads into ``BrokerAccount`` first."""
    rows = [
        {
            "connection_id": connection_id,
            "account_key": account.account_key,
            "account_id": account.account_id,
            "currency": account.currency,
            "account_type": account.account_type,
            "active": account.active,
            "raw": db.Jsonb(account.raw),
        }
        for account in accounts
    ]
    db.upsert_many("broker_accounts", rows, conflict_columns=("connection_id", "account_key"))
    return len(rows)


def record_raw_payload(
    connection_id: int, endpoint: str, params: dict[str, Any], status_code: int, payload: Any
) -> None:
    db.execute(
        sql.INSERT_RAW_PAYLOAD,
        {
            "connection_id": connection_id,
            "endpoint": endpoint,
            "params": db.Jsonb(params),
            "status_code": status_code,
            "payload": db.Jsonb(payload) if payload is not None else None,
        },
    )


class RawPayload(BaseModel):
    id: int
    endpoint: str
    params: dict[str, Any]
    fetched_at: datetime
    status_code: int
    payload: Any


def get_connection(connection_id: int) -> ConnectionStatus | None:
    row = db.select_one(sql.SELECT_CONNECTION, {"id": connection_id})
    return ConnectionStatus.model_validate(row) if row else None


def list_accounts(connection_id: int) -> list[BrokerAccount]:
    return [
        BrokerAccount.model_validate(row) for row in db.select(sql.SELECT_ACCOUNTS, {"connection_id": connection_id})
    ]


def raw_payloads(connection_id: int, endpoint_prefix: str, *, latest_run_only: bool) -> list[RawPayload]:
    """Successful captured responses whose endpoint starts with the prefix, oldest first."""
    return [
        RawPayload.model_validate(row)
        for row in db.select(
            sql.SELECT_RAW_PAYLOADS,
            {
                "connection_id": connection_id,
                "endpoint_prefix": endpoint_prefix + "%",
                "latest_run_only": latest_run_only,
            },
        )
    ]
