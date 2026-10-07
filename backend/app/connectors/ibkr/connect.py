"""Create an IBKR connection from a Flex token and query id; there is no OAuth to go through."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import app.services.connection_service as connections

BROKER = "ibkr"
ENVIRONMENT = "live"
# Client Portal lets a token live up to a year; without a stated expiry that is the assumption.
DEFAULT_TOKEN_LIFETIME = timedelta(days=365)


@dataclass(frozen=True)
class FlexCredentials:
    """The token in the shape ``connection_service`` stores (see ``TokenLike``)."""

    access_token: str
    access_token_expires_at: datetime
    refresh_token: str | None = None
    refresh_token_expires_at: datetime | None = None


def connect(token: str, query_id: str, expires_at: datetime | None = None) -> int:
    token = token.strip()
    query_id = query_id.strip()
    if not token or not query_id:
        raise ValueError("token and query id are required")
    if not query_id.isdigit():
        raise ValueError("the Flex query id is the number shown next to the query in Client Portal")
    expiry = expires_at or datetime.now(UTC) + DEFAULT_TOKEN_LIFETIME
    return connections.save_connection(BROKER, ENVIRONMENT, FlexCredentials(token, expiry), query_id=query_id)


def keep_token_alive(connection_id: int, now: datetime | None = None) -> str:
    """Flex tokens cannot be refreshed: report ``fresh`` or mark the connection ``expired``."""
    connection = connections.load_secrets(connection_id)
    if connection is None:
        raise ValueError(f"connection {connection_id} does not exist")
    if connection.access_token_expires_at <= (now or datetime.now(UTC)):
        connections.mark_token_expired(connection_id, "Flex token expired; generate a new one in Client Portal")
        return "expired"
    return "fresh"
