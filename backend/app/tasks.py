"""Celery tasks: broker syncs, prices, FX, the PnL rebuild and housekeeping."""

from __future__ import annotations

from typing import Any

import app.services.connection_service as connections
from app.celery_app import celery_app
from app.config import settings
from app.connectors.registry import ingest, keep_token_alive, run_sync
from app.services import (
    alert_service,
    fx_service,
    health_service,
    pnl_service,
    price_service,
    settings_service,
)


@celery_app.task(name="returns-portal.verify_health")
def verify_health() -> dict[str, Any]:
    """Run the health checks and email the problems, if any."""
    report = health_service.check_health()
    alert_sent = False
    if not report["healthy"]:
        problems = report["problems"]
        subject = f"[{settings.app_name}][{settings.app_env}] {len(problems)} health problem(s)"
        body = "\n".join(
            [
                f"The {settings.app_name} health check found problems:",
                "",
                *[f"- {problem}" for problem in problems],
                "",
                f"Environment: {settings.app_env}",
                f"Checked at: {report['checked_at']}",
            ]
        )
        alert_sent = alert_service.send_alert(subject, body)
    return {
        "result": "healthy" if report["healthy"] else "problems_found",
        "alert_sent": alert_sent,
        **report,
    }


@celery_app.task(name="returns-portal.sync_connection", soft_time_limit=1500, time_limit=1800)
def sync_connection(connection_id: int) -> dict[str, Any]:
    """Pull a broker connection's data into raw payloads, then map it into the ledger and reconcile."""
    sync_report = run_sync(connection_id).as_dict()
    ingest_report = ingest(connection_id).as_dict()
    return {"sync": sync_report, "ingest": ingest_report}


@celery_app.task(name="returns-portal.refresh_connection", soft_time_limit=1500, time_limit=1800)
def refresh_connection(connection_id: int) -> dict[str, Any]:
    """Everything the dashboard needs after a login or a manual sync, in the daily order: broker sync, FX
    (the ingest converts with it, so it comes first), ingest, prices and the PnL rebuild. Queued by the
    OAuth callback and the "Sync now" button."""
    report: dict[str, Any] = {"sync": run_sync(connection_id).as_dict()}
    try:
        report["fx"] = fx_service.sync_fx().as_dict()
    except Exception as exc:  # ECB unreachable: ingest with the rates already stored
        report["fx"] = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    report["ingest"] = ingest(connection_id).as_dict()
    report["prices"] = price_service.sync_prices(connection_id).as_dict()
    report["pnl"] = pnl_service.rebuild_all()
    return report


@celery_app.task(name="returns-portal.keep_tokens_alive")
def keep_tokens_alive() -> dict[str, Any]:
    """Refresh broker tokens that are close to expiry, so the daily sync never finds a dead refresh token.
    Brokers without refreshable tokens (IBKR Flex) are marked expired once their token lapses."""
    results: dict[str, str] = {}
    for connection in connections.list_connections():
        try:
            results[str(connection.id)] = keep_token_alive(connection.id)
        except Exception as exc:
            results[str(connection.id)] = f"error: {str(exc)[:200]}"
    return {"connections": results}


# Every connection in one task, and a first or full pull can take many minutes per connection.
@celery_app.task(name="returns-portal.sync_all_connections", soft_time_limit=3300, time_limit=3600)
def sync_all_connections() -> dict[str, Any]:
    """Pull every connection and map it into the ledger, so the morning price sync and rebuild see new trades."""
    reports: list[dict[str, Any]] = []
    for connection in connections.list_connections():
        try:
            reports.append({"sync": run_sync(connection.id).as_dict(), "ingest": ingest(connection.id).as_dict()})
        except Exception as exc:
            reports.append({"connection_id": connection.id, "error": str(exc)[:500]})
    return {"connections": reports}


@celery_app.task(name="returns-portal.sync_prices", soft_time_limit=1500, time_limit=1800)
def sync_prices() -> dict[str, Any]:
    """Daily bars for every security: Saxo first, Yahoo for instruments Saxo no longer knows."""
    reports = []
    for connection in connections.list_connections():
        try:
            reports.append(price_service.sync_prices(connection.id).as_dict())
        except Exception as exc:
            reports.append({"connection_id": connection.id, "error": str(exc)[:500]})
    return {"connections": reports}


@celery_app.task(name="returns-portal.sync_fx", soft_time_limit=600, time_limit=900)
def sync_fx() -> dict[str, Any]:
    """ECB reference rates crossed into every base currency in use."""
    return fx_service.sync_fx().as_dict()


@celery_app.task(name="returns-portal.rebuild_pnl", soft_time_limit=1500, time_limit=1800)
def rebuild_pnl() -> dict[str, Any]:
    """Recompute the derived PnL tables for every portfolio from the ledger, prices and FX."""
    return pnl_service.rebuild_all()


@celery_app.task(name="returns-portal.apply_reporting_currency", soft_time_limit=1500, time_limit=1800)
def apply_reporting_currency() -> dict[str, Any]:
    """Re-book every portfolio in the current reporting currency: FX rates crossed into it over the whole
    stored ECB history, every connection's ledger mapped again from its stored payloads (no broker
    requests), then the PnL rebuild. Queued when the reporting currency is changed in Setup."""
    currency = settings_service.reporting_currency()
    report: dict[str, Any] = {"currency": currency, "fx": fx_service.sync_fx().as_dict()}
    report["fx_rows"] = fx_service.rebuild_fx_rates(since=None, bases=[currency])
    ingests: list[dict[str, Any]] = []
    for connection in connections.list_connections():
        try:
            ingests.append(ingest(connection.id).as_dict())
        except Exception as exc:
            ingests.append({"connection_id": connection.id, "error": str(exc)[:500]})
    report["ingest"] = ingests
    report["pnl"] = pnl_service.rebuild_all()
    return report
