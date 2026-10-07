"""Daily health check and the readiness probe.

Each check returns a list of problem descriptions (empty when healthy). The scheduled
``returns-portal.verify_health`` task runs them all and emails the combined problems via
``alert_service``. A job can succeed while its data stays stale (a provider outage, a broker that
stopped sending a section), so the checks look at both: whether each sync ran and succeeded, and
whether the data it feeds (ECB rates, the rebuilt reports) is current.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypedDict

from pydantic import BaseModel, Field
from redis import Redis

from app import db
from app.config import settings
from app.services import connection_service, health_sql
from app.services.connection_service import ConnectionStatus

HealthCheck = Callable[[], list[str]]


class HealthReport(TypedDict):
    healthy: bool
    problems: list[str]
    checked_at: str


class DependencyStatus(BaseModel):
    status: str = Field(description="Dependency state: ok or unavailable.")
    detail: str | None = Field(default=None, description="Safe failure summary when unavailable.")


class ReadinessReport(BaseModel):
    status: str = Field(description="ready only when every required dependency responds.")
    checks: dict[str, DependencyStatus]


# The daily sync runs every morning; a day and a half allows for one slow or retried run.
SYNC_STALE_AFTER = timedelta(hours=36)
# Tokens without a refresh token (IBKR Flex) must be renewed by hand before they lapse.
TOKEN_WARNING = timedelta(days=14)
# The ECB publishes on TARGET working days; five calendar days covers Easter.
ECB_STALE_AFTER = timedelta(days=5)
# The engine rebuilds through yesterday every morning.
REPORTS_STALE_AFTER = timedelta(days=3)


def connection_problems(connections: Sequence[ConnectionStatus], now: datetime) -> list[str]:
    problems: list[str] = []
    for connection in connections:
        name = f"{connection.broker} connection {connection.id}"
        if connection.status == "expired":
            problems.append(f"{name}: access has expired; reconnect it under Setup > Connections")
            continue
        if connection.last_sync_error:
            problems.append(f"{name}: the last sync failed: {connection.last_sync_error[:300]}")
        if connection.last_sync_finished_at is None:
            problems.append(f"{name}: has never finished a sync")
        elif now - connection.last_sync_finished_at > SYNC_STALE_AFTER:
            problems.append(f"{name}: last synced {connection.last_sync_finished_at:%Y-%m-%d %H:%M} UTC")
        if connection.refresh_token_expires_at is None and connection.access_token_expires_at - now < TOKEN_WARNING:
            problems.append(
                f"{name}: its token expires {connection.access_token_expires_at:%Y-%m-%d}; generate a new one"
            )
    return problems


def ecb_problems(last_rate_date: date | None, today: date) -> list[str]:
    if last_rate_date is None:
        return ["No ECB reference rates are stored; run the FX sync"]
    if today - last_rate_date > ECB_STALE_AFTER:
        return [f"The newest ECB reference rate is from {last_rate_date}; the FX sync is not updating"]
    return []


def report_problems(rows: Sequence[dict[str, Any]], today: date) -> list[str]:
    problems: list[str] = []
    for row in rows:
        if row["last_day"] is None:
            problems.append(f"Portfolio {row['name']}: has no rebuilt reports")
        elif today - row["last_day"] > REPORTS_STALE_AFTER:
            problems.append(f"Portfolio {row['name']}: reports end on {row['last_day']}; the PnL rebuild is behind")
    return problems


def _check_connections() -> list[str]:
    return connection_problems(connection_service.list_connections(), datetime.now(UTC))


def _check_ecb_rates() -> list[str]:
    row = db.select_one(health_sql.SELECT_LAST_ECB_RATE) or {}
    return ecb_problems(row.get("last_date"), datetime.now(UTC).date())


def _check_reports() -> list[str]:
    return report_problems(db.select(health_sql.SELECT_LAST_PORTFOLIO_DAYS), datetime.now(UTC).date())


HEALTH_CHECKS: tuple[HealthCheck, ...] = (_check_connections, _check_ecb_rates, _check_reports)


def check_health(checks: Sequence[HealthCheck] | None = None) -> HealthReport:
    problems = [problem for check in (checks or HEALTH_CHECKS) for problem in check()]
    return {
        "healthy": not problems,
        "problems": problems,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def check_readiness() -> ReadinessReport:
    checks: dict[str, DependencyStatus] = {}
    try:
        db.select_one(health_sql.SELECT_READY)
        checks["postgres"] = DependencyStatus(status="ok")
    except Exception as exc:
        checks["postgres"] = DependencyStatus(status="unavailable", detail=type(exc).__name__)

    try:
        with Redis.from_url(
            settings.celery_broker_url,
            socket_connect_timeout=1,
            socket_timeout=1,
        ) as redis_client:
            redis_client.ping()
        checks["redis"] = DependencyStatus(status="ok")
    except Exception as exc:
        checks["redis"] = DependencyStatus(status="unavailable", detail=type(exc).__name__)

    ready = all(check.status == "ok" for check in checks.values())
    return ReadinessReport(status="ready" if ready else "not_ready", checks=checks)
