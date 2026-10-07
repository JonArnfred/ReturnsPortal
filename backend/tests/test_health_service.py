from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.services.connection_service import ConnectionStatus
from app.services.health_service import check_health, connection_problems, ecb_problems, report_problems

NOW = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)


def connection(**overrides: Any) -> ConnectionStatus:
    fields: dict[str, Any] = {
        "id": 1,
        "broker": "ibkr",
        "environment": "live",
        "client_key": None,
        "client_name": None,
        "base_currency": "EUR",
        "status": "connected",
        "account_count": 1,
        "access_token_expires_at": NOW + timedelta(days=200),
        "refresh_token_expires_at": None,
        "last_sync_started_at": NOW - timedelta(hours=3),
        "last_sync_finished_at": NOW - timedelta(hours=2),
        "last_sync_error": None,
        "last_success_finished_at": NOW - timedelta(hours=2),
        "created_at": NOW - timedelta(days=30),
    }
    fields.update(overrides)
    return ConnectionStatus(**fields)


def test_healthy_when_no_check_reports_problems() -> None:
    report = check_health(checks=[lambda: []])
    assert report["healthy"] is True
    assert report["problems"] == []
    assert report["checked_at"]


def test_collects_problems_across_checks() -> None:
    report = check_health(checks=[lambda: ["stale table"], lambda: [], lambda: ["job never ran"]])
    assert report["healthy"] is False
    assert report["problems"] == ["stale table", "job never ran"]


def test_a_recent_successful_sync_is_healthy() -> None:
    assert connection_problems([connection()], NOW) == []


def test_connection_problems() -> None:
    [failed] = connection_problems([connection(last_sync_error="Flex SendRequest answered HTTP 503")], NOW)
    assert "last sync failed" in failed and "HTTP 503" in failed
    [stale] = connection_problems([connection(last_sync_finished_at=NOW - timedelta(days=3))], NOW)
    assert "last synced 2026-10-04" in stale
    [never] = connection_problems([connection(last_sync_finished_at=None)], NOW)
    assert "never finished" in never
    [expired] = connection_problems([connection(status="expired", last_sync_error="token expired")], NOW)
    assert "reconnect" in expired


def test_only_tokens_without_refresh_warn_before_expiry() -> None:
    soon = NOW + timedelta(days=5)
    [warning] = connection_problems([connection(access_token_expires_at=soon)], NOW)
    assert "expires 2026-10-12" in warning
    refreshed = connection(broker="saxo", access_token_expires_at=soon, refresh_token_expires_at=soon)
    assert connection_problems([refreshed], NOW) == []


def test_ecb_and_report_freshness() -> None:
    today = date(2026, 10, 7)
    assert ecb_problems(date(2026, 10, 6), today) == []
    assert "not updating" in ecb_problems(date(2026, 9, 30), today)[0]
    assert "No ECB" in ecb_problems(None, today)[0]
    rows: list[dict[str, Any]] = [
        {"name": "Current", "last_day": date(2026, 10, 6)},
        {"name": "Behind", "last_day": date(2026, 9, 1)},
        {"name": "New", "last_day": None},
    ]
    assert report_problems(rows, today) == [
        "Portfolio Behind: reports end on 2026-09-01; the PnL rebuild is behind",
        "Portfolio New: has no rebuilt reports",
    ]
