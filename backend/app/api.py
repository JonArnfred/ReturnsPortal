"""Litestar application assembly."""

from __future__ import annotations

from litestar import Litestar
from litestar.config.allowed_hosts import AllowedHostsConfig
from litestar.config.cors import CORSConfig

from app.config import settings
from app.db import close_pool
from app.http import before_request, before_send, handle_exception
from app.openapi import openapi_config
from app.routes.connections import routes as connection_routes
from app.routes.fx import routes as fx_routes
from app.routes.health import live, ready
from app.routes.ledger import routes as ledger_routes
from app.routes.preferences import routes as preference_routes
from app.routes.prices import routes as price_routes
from app.routes.reports import routes as report_routes
from app.routes.settings import routes as settings_routes

cors_config = CORSConfig(allow_origins=list(settings.cors_allowed_origins)) if settings.cors_allowed_origins else None

app = Litestar(
    route_handlers=[
        live,
        ready,
        *connection_routes,
        *ledger_routes,
        *preference_routes,
        *price_routes,
        *fx_routes,
        *report_routes,
        *settings_routes,
    ],
    allowed_hosts=AllowedHostsConfig(allowed_hosts=settings.allowed_host_headers, www_redirect=False),
    cors_config=cors_config,
    request_max_body_size=settings.request_max_body_size,
    before_request=before_request,
    before_send=[before_send],
    exception_handlers={Exception: handle_exception},
    on_shutdown=[lambda _: close_pool()],
    openapi_config=openapi_config,
)
