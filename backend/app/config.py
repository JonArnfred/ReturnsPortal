"""Runtime configuration loaded from environment variables and backend/.env."""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from urllib.parse import parse_qs, quote

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")
if os.environ.get("FLOWER_BASIC_AUTH") == "":
    os.environ.pop("FLOWER_BASIC_AUTH")


def _build_database_url() -> str:
    """From the DB_* settings when DB_USERNAME is set (DATABASE_URL is then ignored), else DATABASE_URL."""
    username = os.environ.get("DB_USERNAME")
    if username:
        password = os.environ.get("DB_PASSWORD", "")
        host = os.environ.get("DB_HOST", "127.0.0.1")
        port = os.environ.get("DB_PORT", "5432")
        database = os.environ.get("DB_DATABASE") or "returns_portal"
        # dbmate reads this URL too, and its driver knows disable, require, verify-ca and verify-full.
        sslmode = os.environ.get("DB_SSLMODE", "disable")
        return (
            f"postgres://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}/{database}"
            f"?sslmode={quote(sslmode, safe='')}"
        )
    return os.environ.get(
        "DATABASE_URL",
        "postgres://returns_portal:returns_portal@localhost:5432/returns_portal?sslmode=disable",
    )


def _build_redis_url() -> str:
    protocol = os.environ.get("REDIS_PROTOCOL")
    if protocol:
        username = os.environ.get("REDIS_USERNAME", "")
        password = os.environ.get("REDIS_PASSWORD", "")
        host = os.environ.get("REDIS_HOST", "127.0.0.1")
        port = os.environ.get("REDIS_PORT", "6379")
        database = os.environ.get("REDIS_DATABASE", "0")
        params = os.environ.get("REDIS_CONNECTION_PARAMS", "")
        auth = ""
        if password:
            user = username or "default"
            auth = f"{quote(user, safe='')}:{quote(password, safe='')}@"
        return f"{protocol}{auth}{host}:{port}/{database}{params}"
    return os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")


def _build_redis_ssl_options() -> dict[str, object] | None:
    protocol = os.environ.get("REDIS_PROTOCOL")
    if protocol != "rediss://":
        return None
    params = parse_qs(os.environ.get("REDIS_CONNECTION_PARAMS", "").lstrip("?"))
    options: dict[str, object] = {}
    cert_reqs = params.get("ssl_cert_reqs", [None])[0]
    if cert_reqs:
        options["ssl_cert_reqs"] = {
            "required": ssl.CERT_REQUIRED,
            "optional": ssl.CERT_OPTIONAL,
            "none": ssl.CERT_NONE,
        }.get(cert_reqs.lower(), ssl.CERT_REQUIRED)
    check_hostname = params.get("ssl_check_hostname", [None])[0]
    if check_hostname is not None:
        options["ssl_check_hostname"] = check_hostname.lower() == "true"
    return options or None


def _choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    """A setting with a fixed set of values; a typo fails at startup instead of halfway through a login."""
    value = os.environ.get(name, default).strip().lower() or default
    if value not in choices:
        raise ValueError(f"{name} must be one of {', '.join(choices)}, not {value!r}")
    return value


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(value.strip() for value in os.environ.get(name, default).split(",") if value.strip())


class Settings:
    app_name: str = os.environ.get("APP_NAME", "returns-portal")
    app_env: str = os.environ.get("APP_ENV", "production")
    api_port: int = int(os.environ.get("API_PORT", "18020"))
    allowed_hosts: tuple[str, ...] = _csv("ALLOWED_HOSTS", "localhost,127.0.0.1")
    cors_allowed_origins: tuple[str, ...] = _csv("CORS_ALLOWED_ORIGINS")
    request_max_body_size: int = int(os.environ.get("REQUEST_MAX_BODY_SIZE", "1000000"))

    @property
    def allowed_host_headers(self) -> list[str]:
        """Litestar currently matches the complete Host header, including its port."""
        if "*" in self.allowed_hosts:
            return ["*"]
        return [
            *self.allowed_hosts,
            *(f"{host}:{self.api_port}" for host in self.allowed_hosts if ":" not in host),
        ]

    database_url: str = _build_database_url()

    celery_broker_url: str = _build_redis_url()
    celery_result_backend: str = _build_redis_url()
    celery_redis_ssl_options: dict[str, object] | None = _build_redis_ssl_options()

    alert_email_user: str | None = os.environ.get("ALERT_EMAIL_USER") or None
    alert_email_password: str | None = os.environ.get("ALERT_EMAIL_PASSWORD") or None
    alert_smtp_host: str = os.environ.get("ALERT_SMTP_HOST", "")
    alert_smtp_port: int = int(os.environ.get("ALERT_SMTP_PORT", "587"))

    health_check_cron_hour: str = os.environ.get("HEALTH_CHECK_CRON_HOUR", "7")
    health_check_cron_minute: int = int(os.environ.get("HEALTH_CHECK_CRON_MINUTE", "0"))

    # Where browser redirects land after an OAuth callback (the SSR frontend origin).
    frontend_origin: str = os.environ.get("FRONTEND_ORIGIN", "http://localhost:25183")

    # The user's currency: every portfolio is booked, valued and reported in it. A broker whose own
    # base currency differs is converted with the ECB rates the engine already uses.
    reporting_currency: str = os.environ.get("REPORTING_CURRENCY", "EUR").upper()

    # Fernet key protecting broker tokens at rest; generate with backend/scripts/generate_encryption_key.py.
    secrets_encryption_key: str | None = os.environ.get("SECRETS_ENCRYPTION_KEY") or None

    saxo_app_key: str | None = os.environ.get("SAXO_APP_KEY") or None
    saxo_app_secret: str | None = os.environ.get("SAXO_APP_SECRET") or None
    saxo_environment: str = _choice("SAXO_ENVIRONMENT", "live", ("live", "sim"))
    saxo_redirect_uri: str = os.environ.get("SAXO_REDIRECT_URI", "http://localhost:25183/api/connections/saxo/callback")
    saxo_history_start: str = os.environ.get("SAXO_HISTORY_START", "2010-01-01")

    # IBKR Flex Web Service: token and Activity Flex Query id, used by scripts/connect_ibkr.py to create the
    # connection (the UI form is the other way in). The token is generated in Client Portal and expires.
    ibkr_flex_token: str | None = os.environ.get("IBKR_FLEX_TOKEN") or None
    ibkr_flex_query_id: str | None = os.environ.get("IBKR_FLEX_QUERY_ID") or None
    # Earliest day to pull on the first sync; empty means the account's opening date from the report.
    ibkr_history_start: str | None = os.environ.get("IBKR_HISTORY_START") or None


settings = Settings()
