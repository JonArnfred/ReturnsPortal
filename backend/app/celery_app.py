"""Celery application: Redis broker/result backend and the daily schedule."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery("returns_portal", broker=settings.celery_broker_url, backend=settings.celery_result_backend)

celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_track_started=True,
    worker_send_task_events=True,
    task_send_sent_event=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_soft_time_limit=270,
    task_time_limit=300,
    result_expires=3600,
    worker_prefetch_multiplier=1,
)

if settings.celery_redis_ssl_options is not None:
    celery_app.conf.broker_use_ssl = settings.celery_redis_ssl_options
    celery_app.conf.redis_backend_use_ssl = settings.celery_redis_ssl_options

celery_app.conf.beat_schedule = {
    # After the morning FX sync, broker syncs and PnL rebuild (all UTC), so a broken run is caught the
    # same day.
    "verify-health-daily": {
        "task": "returns-portal.verify_health",
        "schedule": crontab(hour=settings.health_check_cron_hour, minute=settings.health_check_cron_minute),
    },
    # Saxo refresh tokens live one hour; refreshing every 20 minutes keeps the connection alive
    # across the day without a new login.
    "keep-tokens-alive": {
        "task": "returns-portal.keep_tokens_alive",
        "schedule": crontab(minute="*/20"),
    },
    # Brokers publish end-of-day data overnight; Saxo history is complete by early morning CET.
    # ECB publishes around 16:00 CET; the morning run picks up yesterday's fixing. Before the broker
    # sync, because the ingest converts amounts into the reporting currency with these rates.
    "sync-fx-daily": {
        "task": "returns-portal.sync_fx",
        "schedule": crontab(hour="4", minute="15"),
    },
    "sync-all-connections-daily": {
        "task": "returns-portal.sync_all_connections",
        "schedule": crontab(hour="4", minute="30"),
    },
    # After the broker sync, so newly traded instruments get prices the same morning.
    "sync-prices-daily": {
        "task": "returns-portal.sync_prices",
        "schedule": crontab(hour="5", minute="15"),
    },
    # After prices and FX are in, so the derived tables reflect the full day.
    "rebuild-pnl-daily": {
        "task": "returns-portal.rebuild_pnl",
        "schedule": crontab(hour="5", minute="50"),
    },
}

import app.tasks  # noqa: E402,F401
