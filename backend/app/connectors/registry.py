"""Which connector serves a connection. Tasks and scripts dispatch on ``broker_connections.broker``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import app.services.connection_service as connections


class Report(Protocol):
    def as_dict(self) -> dict[str, Any]: ...


class SyncFunction(Protocol):
    """Capture a connection's data; ``full`` pulls the whole history again instead of the days since
    the last successful sync."""

    def __call__(self, connection_id: int, *, full: bool = False) -> Report: ...


@dataclass(frozen=True)
class Connector:
    broker: str
    run_sync: SyncFunction
    ingest: Callable[[int], Report]
    keep_token_alive: Callable[[int], str]


def connector(broker: str) -> Connector:
    # Imported lazily: the connector modules pull in HTTP clients and services the caller may not need.
    if broker == "saxo":
        from app.connectors.saxo import ingest as saxo_ingest
        from app.connectors.saxo import sync as saxo_sync

        return Connector("saxo", saxo_sync.run_sync, saxo_ingest.ingest, saxo_sync.keep_token_alive)
    if broker == "ibkr":
        from app.connectors.ibkr import connect as ibkr_connect
        from app.connectors.ibkr import ingest as ibkr_ingest
        from app.connectors.ibkr import sync as ibkr_sync

        return Connector("ibkr", ibkr_sync.run_sync, ibkr_ingest.ingest, ibkr_connect.keep_token_alive)
    raise ValueError(f"no connector for broker {broker!r}")


def connector_for(connection_id: int) -> Connector:
    connection = connections.get_connection(connection_id)
    if connection is None:
        raise ValueError(f"connection {connection_id} does not exist")
    return connector(connection.broker)


def run_sync(connection_id: int, *, full: bool = False) -> Report:
    return connector_for(connection_id).run_sync(connection_id, full=full)


def ingest(connection_id: int) -> Report:
    return connector_for(connection_id).ingest(connection_id)


def keep_token_alive(connection_id: int) -> str:
    return connector_for(connection_id).keep_token_alive(connection_id)
