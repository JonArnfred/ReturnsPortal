"""Pull Activity Flex statements and store every section as a raw payload.

Capture stage only; nothing is mapped here. The first sync pulls a short bootstrap statement to
learn the account's opening date, then the history in windows of at most a year (the service's
limit per pull). Later syncs pull the days since the last successful sync plus a few of overlap;
the ingest is idempotent, so overlap is harmless. Every statement lands in ``broker_raw_payloads``
as one row per section, endpoint ``flex/statement/<Section>``; failed requests land under
``flex/error`` with the service's error code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import app.services.connection_service as connections
from app.config import settings
from app.connectors.ibkr import mapping
from app.connectors.ibkr.client import FlexClient, window_params
from app.connectors.ibkr.dto import FlexAccountInformation, FlexStatementData, parse_statements

logger = logging.getLogger("returns-portal.ibkr")

BOOTSTRAP_DAYS = 7
INCREMENTAL_OVERLAP_DAYS = 3
MIN_INCREMENTAL_DAYS = 7
MAX_WINDOW_DAYS = 365
WINDOW_PAUSE_SECONDS = 2.0
ERROR_ENDPOINT = "flex/error"
# A window the service cannot serve (error 1003, typically a range before the account existed) is
# recorded and skipped; anything else stops the sync.
SKIPPABLE_CODES = frozenset({"1003"})


@dataclass
class SyncReport:
    connection_id: int
    started_at: datetime
    requests: int = 0
    stored_payloads: int = 0
    failures: list[str] = field(default_factory=list)
    accounts: int = 0
    windows: list[dict[str, str]] = field(default_factory=list)
    finished_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "requests": self.requests,
            "stored_payloads": self.stored_payloads,
            "accounts": self.accounts,
            "windows": self.windows,
            "failures": self.failures,
        }


def windows(start: date, end: date, max_days: int = MAX_WINDOW_DAYS) -> list[tuple[date, date]]:
    """Consecutive ranges of at most ``max_days`` days covering ``start``..``end``."""
    result: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=max_days - 1), end)
        result.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return result


def last_weekday_before(day: date) -> date:
    """The service refuses an end date without a statement, so windows end on the last weekday
    strictly before ``day``."""
    cursor = day - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def incremental_days(last_success: datetime, today: date) -> int:
    days = (today - last_success.date()).days + INCREMENTAL_OVERLAP_DAYS
    return max(MIN_INCREMENTAL_DAYS, min(MAX_WINDOW_DAYS, days))


def run_sync(
    connection_id: int, client: FlexClient | None = None, today: date | None = None, *, full: bool = False
) -> SyncReport:
    """Capture new statements. ``full`` pulls the whole history again, as the first sync does; use it
    once after adding a section to the Flex query."""
    report = SyncReport(connection_id=connection_id, started_at=datetime.now(UTC))
    connection = connections.load_secrets(connection_id)
    status = connections.get_connection(connection_id)
    if connection is None or status is None:
        raise ValueError(f"connection {connection_id} does not exist")
    if not connection.query_id:
        raise RuntimeError("the IBKR connection has no Flex query id; reconnect the broker")
    # Incremental from the last good sync: a failed one does not make the next pull the whole history.
    last_success = None if full else status.last_success_finished_at
    connections.mark_sync_started(connection_id)
    owned_client = client is None
    try:
        client = client or FlexClient(connection.access_token)
        _capture(report, connection, client, today or datetime.now(UTC).date(), last_success)
        connections.mark_sync_finished(connection_id, error=None)
    except Exception as exc:
        logger.exception("IBKR sync failed for connection %s", connection_id)
        connections.mark_sync_finished(connection_id, error=str(exc)[:1000])
        raise
    finally:
        if owned_client and client is not None:
            client.close()
        report.finished_at = datetime.now(UTC)
    return report


def _capture(
    report: SyncReport,
    connection: connections.ConnectionSecrets,
    client: FlexClient,
    today: date,
    last_success: datetime | None,
) -> None:
    query_id = connection.query_id or ""
    if last_success is not None:
        _pull(report, connection, client, window_params(query_id, period_days=incremental_days(last_success, today)))
        return

    # First sync: a short statement tells us when the account was opened.
    statements = _pull(report, connection, client, window_params(query_id, period_days=BOOTSTRAP_DAYS))
    opened = [
        info.date_opened
        for statement in statements
        for info, _ in _account_information(statement)
        if info.date_opened is not None
    ]
    configured = date.fromisoformat(settings.ibkr_history_start) if settings.ibkr_history_start else None
    start = configured or (min(opened) if opened else today - timedelta(days=MAX_WINDOW_DAYS - 1))
    end = last_weekday_before(today)
    if start > end:
        return
    if (today - start).days < MAX_WINDOW_DAYS:
        # Young account: one pull by period, which needs no end-date bookkeeping.
        client.sleep(WINDOW_PAUSE_SECONDS)
        _pull(report, connection, client, window_params(query_id, period_days=(today - start).days + 1))
        return
    for window_start, window_end in windows(start, end):
        client.sleep(WINDOW_PAUSE_SECONDS)
        _pull(report, connection, client, window_params(query_id, from_date=window_start, to_date=window_end))


def _pull(
    report: SyncReport, connection: connections.ConnectionSecrets, client: FlexClient, params: dict[str, str]
) -> list[FlexStatementData]:
    result = client.fetch_statement(params)
    report.requests += 1
    window = {key: value for key, value in params.items() if key in ("p", "fd", "td")}
    if not result.ok:
        connections.record_raw_payload(
            connection.id,
            ERROR_ENDPOINT,
            params,
            502,
            {
                "ErrorCode": result.error_code,
                "ErrorMessage": result.error_message,
                "ReferenceCode": result.reference_code,
            },
        )
        report.stored_payloads += 1
        message = f"{window}: {result.error_code} {result.error_message or ''}".strip()
        report.failures.append(message)
        if result.credential_problem:
            connections.mark_token_expired(connection.id, f"Flex token rejected: {message}")
            raise RuntimeError(f"Flex token rejected ({result.error_code}); generate a new token and reconnect")
        if result.error_code in SKIPPABLE_CODES:
            logger.warning("Flex statement unavailable for %s; skipping", window)
            return []
        raise RuntimeError(f"Flex request failed: {message}")
    try:
        statements = parse_statements(result.text)
    except Exception as exc:
        # Keep what the service sent, so it can be looked at without asking (and being throttled) again.
        connections.record_raw_payload(
            connection.id, ERROR_ENDPOINT, params, 502, {"ParseError": str(exc)[:500], "Text": result.text}
        )
        report.stored_payloads += 1
        raise
    # Before anything is stored: another client's data must not land in this connection.
    connections.ensure_same_client(
        connection, [info.account_id for statement in statements for info, _ in _account_information(statement)]
    )
    for statement in statements:
        report.windows.append({**window, **statement.attributes})
        _store_statement(report, connection, params, statement)
    return statements


def _store_statement(
    report: SyncReport, connection: connections.ConnectionSecrets, params: dict[str, str], statement: FlexStatementData
) -> None:
    for section, rows in statement.sections.items():
        if section == "AccountInformation":
            rows = [mapping.strip_account_information(row) for row in rows]
        connections.record_raw_payload(
            connection.id,
            f"{mapping.STATEMENT_ENDPOINT}{section}",
            {**params, **statement.attributes},
            200,
            {"statement": statement.attributes, "rows": rows},
        )
        report.stored_payloads += 1
    infos = _account_information(statement)
    if infos:
        report.accounts += connections.upsert_account_records(
            connection.id, [mapping.map_account(info, row) for info, row in infos]
        )
        first, _ = infos[0]
        connections.update_client_details(
            connection.id, client_key=first.account_id, client_name=first.name, base_currency=first.currency
        )


def _account_information(statement: FlexStatementData) -> list[tuple[FlexAccountInformation, dict[str, str]]]:
    return [
        (FlexAccountInformation.model_validate(row), row)
        for row in statement.sections.get("AccountInformation", [])
        if row.get("accountId")
    ]
