"""Pull everything the Saxo account exposes and store the raw payloads.

This is the capture stage: nothing is mapped to the ledger yet. Every response, including
failures, is written to ``broker_raw_payloads`` so the mapping can be built and replayed
against real data. Historical report endpoints are pulled in yearly windows: the whole history on
the first sync (and with ``full``), afterwards only the days since the last successful sync plus an
overlap. The ingest reads every stored report payload, so older history stays in the ledger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

import app.services.connection_service as connections
from app.config import settings
from app.connectors.saxo import auth, mapping
from app.connectors.saxo.client import FetchResult, SaxoClient
from app.connectors.saxo.dto import SaxoAccount, SaxoClientInfo

logger = logging.getLogger("returns-portal.saxo")

POSITION_FIELD_GROUPS = "PositionBase,PositionView,DisplayAndFormat,ExchangeInfo"
REFRESH_MARGIN = timedelta(minutes=5)
# Saxo live tokens: access 20 minutes, refresh 60 minutes, and every refresh issues a new pair. A
# connection therefore has to be refreshed at least hourly or the user must authorize again.
KEEP_ALIVE_MARGIN = timedelta(minutes=30)

# Client Services report endpoints, pulled per client key in yearly windows. The trades report
# carries quantities and prices; the bookings report is the complete cash ledger.
HISTORY_REPORTS = ("trades", "bookings")
# Order history is the audit log of order events (placed, filled, cancelled...), also pulled per client
# key in yearly windows. Working orders come from the portfolio endpoint.
ORDER_ACTIVITIES = "cs/v1/audit/orderactivities"
ORDER_FIELD_GROUPS = "DisplayAndFormat,ExchangeInfo"
INSTRUMENT_BATCH = 50
# Re-pull this many days before the last successful sync: bookings can arrive a few days after the
# trade (value dates, corrections), and the ingest collapses repeats on Saxo's identifiers.
INCREMENTAL_OVERLAP_DAYS = 14


@dataclass
class SyncReport:
    connection_id: int
    started_at: datetime
    requests: int = 0
    stored_payloads: int = 0
    failures: list[str] = field(default_factory=list)
    accounts: int = 0
    finished_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "requests": self.requests,
            "stored_payloads": self.stored_payloads,
            "accounts": self.accounts,
            "failures": self.failures,
        }


def _year_windows(start: date, end: date) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(date(cursor.year, 12, 31), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _ensure_fresh_token(connection: connections.ConnectionSecrets) -> str:
    """Return a usable access token, refreshing and persisting it when close to expiry."""
    now = datetime.now(UTC)
    if connection.access_token_expires_at - now > REFRESH_MARGIN:
        return connection.access_token
    if not connection.refresh_token:
        raise RuntimeError("access token expired and no refresh token is stored; reconnect the broker")
    tokens = auth.refresh_tokens(connection.refresh_token, connection.environment)
    connections.store_tokens(connection.id, tokens)
    return tokens.access_token


def current_token(connection_id: int) -> str:
    """The stored access token (the keep-alive task may have refreshed it), refreshed when near expiry."""
    connection = connections.load_secrets(connection_id)
    if connection is None:
        raise ValueError(f"connection {connection_id} does not exist")
    return _ensure_fresh_token(connection)


def client_for(connection: connections.ConnectionSecrets) -> SaxoClient:
    return SaxoClient(
        _ensure_fresh_token(connection),
        auth.endpoints(connection.environment).api_base,
        token_provider=lambda: current_token(connection.id),
    )


def keep_token_alive(connection_id: int, now: datetime | None = None) -> str:
    """Refresh the token pair when either token is within ``KEEP_ALIVE_MARGIN`` of expiry.

    Returns ``refreshed``, ``fresh`` (nothing to do), ``no_refresh_token`` or ``expired`` (the
    broker rejected the refresh token; the connection is marked expired for the UI).
    """
    connection = connections.load_secrets(connection_id)
    if connection is None:
        raise ValueError(f"connection {connection_id} does not exist")
    if not connection.refresh_token:
        return "no_refresh_token"
    current = now or datetime.now(UTC)
    refresh_expiry = connection.refresh_token_expires_at
    due = connection.access_token_expires_at - current <= KEEP_ALIVE_MARGIN or (
        refresh_expiry is not None and refresh_expiry - current <= KEEP_ALIVE_MARGIN
    )
    if not due:
        return "fresh"
    try:
        tokens = auth.refresh_tokens(connection.refresh_token, connection.environment)
    except httpx.HTTPStatusError as exc:
        if 400 <= exc.response.status_code < 500:
            logger.warning("Saxo refused the refresh token for connection %s: %s", connection_id, exc)
            connections.mark_token_expired(connection_id, f"token refresh rejected: {exc}")
            return "expired"
        raise
    connections.store_tokens(connection_id, tokens)
    return "refreshed"


def _store(report: SyncReport, connection_id: int, results: list[FetchResult]) -> None:
    for result in results:
        report.requests += 1
        connections.record_raw_payload(
            connection_id, result.endpoint, result.params, result.status_code, result.payload
        )
        report.stored_payloads += 1
        if not result.ok:
            report.failures.append(f"{result.endpoint} {result.params} -> HTTP {result.status_code}")


def history_start(last_success: datetime | None) -> date:
    """First day of the report windows: the configured start, or shortly before the last good sync."""
    start = date.fromisoformat(settings.saxo_history_start)
    if last_success is None:
        return start
    return max(start, last_success.date() - timedelta(days=INCREMENTAL_OVERLAP_DAYS))


def run_sync(
    connection_id: int, client: SaxoClient | None = None, today: date | None = None, *, full: bool = False
) -> SyncReport:
    """Capture the account. ``full`` pulls the whole report history again, as the first sync does."""
    report = SyncReport(connection_id=connection_id, started_at=datetime.now(UTC))
    connection = connections.load_secrets(connection_id)
    status = connections.get_connection(connection_id)
    if connection is None or status is None:
        raise ValueError(f"connection {connection_id} does not exist")
    # Incremental from the last good sync: a failed one does not make the next pull the whole history.
    last_success = None if full else status.last_success_finished_at
    connections.mark_sync_started(connection_id)
    owned_client = client is None
    try:
        if client is None:
            client = client_for(connection)
        _capture(report, connection, client, today or datetime.now(UTC).date(), history_start(last_success))
        connections.mark_sync_finished(connection_id, error=None)
    except Exception as exc:
        logger.exception("Saxo sync failed for connection %s", connection_id)
        connections.mark_sync_finished(connection_id, error=str(exc)[:1000])
        raise
    finally:
        if owned_client and client is not None:
            client.close()
        report.finished_at = datetime.now(UTC)
    return report


def _capture(
    report: SyncReport, connection: connections.ConnectionSecrets, client: SaxoClient, today: date, start: date
) -> None:
    me = client.fetch("port/v1/clients/me")
    if me.ok and isinstance(me.payload, dict) and me.payload.get("ClientKey"):
        # Before anything is stored: another client's data must not land in this connection.
        connections.ensure_same_client(connection, [str(me.payload["ClientKey"])])
    _store(report, connection.id, [me])
    if not me.ok or not isinstance(me.payload, dict):
        raise RuntimeError(f"port/v1/clients/me failed with HTTP {me.status_code}")
    info = SaxoClientInfo.model_validate(me.payload)
    client_key = info.client_key
    connections.update_client_details(
        connection.id, client_key=client_key, client_name=info.name or None, base_currency=info.default_currency
    )

    accounts = client.fetch_pages("port/v1/accounts/me")
    _store(report, connection.id, accounts)
    account_records = [
        mapping.map_account(SaxoAccount.model_validate(row), row)
        for page in accounts
        for row in page.data
        if isinstance(row, dict) and row.get("AccountKey")
    ]
    report.accounts = connections.upsert_account_records(connection.id, account_records)

    scoped = {"ClientKey": client_key}
    instruments: set[tuple[int, str]] = set()
    # port/v1/closedpositions is deliberately absent: retail clients run in end-of-day netting
    # mode, where Saxo answers HTTP 400 for it. The bookings report covers closed positions.
    for endpoint, params in (
        ("port/v1/positions", {**scoped, "FieldGroups": POSITION_FIELD_GROUPS}),
        ("port/v1/netpositions", {**scoped, "FieldGroups": "NetPositionBase,NetPositionView,DisplayAndFormat"}),
        ("port/v1/balances", scoped),
    ):
        pages = client.fetch_pages(endpoint, params)
        _store(report, connection.id, pages)
        if endpoint == "port/v1/positions":
            for row in (row for page in pages for row in page.data if isinstance(row, dict)):
                base = row.get("PositionBase") or {}
                if base.get("Uic") and base.get("AssetType"):
                    instruments.add((int(base["Uic"]), str(base["AssetType"])))
    for account in account_records:
        _store(
            report, connection.id, client.fetch_pages("port/v1/balances", {**scoped, "AccountKey": account.account_key})
        )

    open_orders = client.fetch_pages("port/v1/orders/me", {"FieldGroups": ORDER_FIELD_GROUPS})
    _store(report, connection.id, open_orders)
    for row in (row for page in open_orders for row in page.data if isinstance(row, dict)):
        if row.get("Uic") and row.get("AssetType"):
            instruments.add((int(row["Uic"]), str(row["AssetType"])))

    for report_name in HISTORY_REPORTS:
        endpoint = f"cs/v1/reports/{report_name}/{client_key}"
        for window_start, window_end in _year_windows(start, today):
            pages = client.fetch_pages(
                endpoint, {"FromDate": window_start.isoformat(), "ToDate": window_end.isoformat()}
            )
            _store(report, connection.id, pages)
            if pages and pages[0].status_code == 404:
                logger.warning("Saxo report %s is not available (HTTP 404); skipping remaining windows", endpoint)
                break
            if report_name == "trades":
                for row in (row for page in pages for row in page.data if isinstance(row, dict)):
                    if row.get("Uic") and row.get("AssetType"):
                        instruments.add((int(row["Uic"]), str(row["AssetType"])))

    for window_start, window_end in _year_windows(start, today):
        pages = client.fetch_pages(
            ORDER_ACTIVITIES,
            {
                **scoped,
                "FromDateTime": f"{window_start.isoformat()}T00:00:00Z",
                "ToDateTime": f"{window_end.isoformat()}T23:59:59Z",
            },
        )
        _store(report, connection.id, pages)
        if pages and pages[0].status_code == 404:
            logger.warning("Saxo order activities are not available (HTTP 404); skipping remaining windows")
            break
        for row in (row for page in pages for row in page.data if isinstance(row, dict)):
            if row.get("Uic") and row.get("AssetType"):
                instruments.add((int(row["Uic"]), str(row["AssetType"])))

    # Reference data: exchange ids to MICs, and instrument currency/symbol for every Uic traded in the
    # pulled windows, held or ordered (details from earlier syncs stay stored for older trades).
    _store(report, connection.id, client.fetch_pages("ref/v1/exchanges", {"$top": "500"}))
    by_asset_type: dict[str, list[int]] = {}
    for uic, asset_type in sorted(instruments):
        by_asset_type.setdefault(asset_type, []).append(uic)
    for asset_type, uics in by_asset_type.items():
        for offset in range(0, len(uics), INSTRUMENT_BATCH):
            batch = uics[offset : offset + INSTRUMENT_BATCH]
            _store(
                report,
                connection.id,
                client.fetch_pages(
                    "ref/v1/instruments/details",
                    {"Uics": ",".join(str(uic) for uic in batch), "AssetTypes": asset_type},
                ),
            )
