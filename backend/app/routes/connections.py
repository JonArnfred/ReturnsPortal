"""Broker connections: Saxo OAuth flow, IBKR Flex credentials, connection status, and sync triggers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlencode

from litestar import get, post
from litestar.datastructures import Cookie
from litestar.exceptions import NotFoundException, ServiceUnavailableException, ValidationException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import CookieParameter, FromPath, FromQuery, QueryParameter
from litestar.response import Redirect
from pydantic import BaseModel, Field

from app.config import settings
from app.connectors.ibkr import connect as ibkr
from app.connectors.saxo import auth
from app.openapi import standard_error_responses
from app.services import connection_service as connections
from app.services.connection_service import ConnectionStatus

logger = logging.getLogger("returns-portal.connections")

CONNECTIONS_PAGE = "/setup/connections"
# The OAuth state is also kept in a cookie of the browser that started the login, so a callback link
# crafted from someone else's login (their code and state) cannot connect their account here.
OAUTH_STATE_COOKIE = "rp_saxo_oauth_state"
OAUTH_COOKIE_PATH = "/api/connections/saxo"


class ConnectionsResponse(BaseModel):
    connections: list[ConnectionStatus] = Field(description="All broker connections, without token material.")


class SyncQueuedResponse(BaseModel):
    connection_id: int = Field(description="Connection whose sync was queued.", examples=[1])
    task_id: str = Field(description="Celery task identifier for the queued sync.")


class IbkrConnectRequest(BaseModel):
    token: str = Field(description="Flex Web Service token generated in Client Portal.", min_length=8)
    query_id: str = Field(description="Id of the Activity Flex Query to pull.", examples=["123456"], min_length=1)
    expires_at: datetime | None = Field(
        default=None,
        description="When the token expires, as chosen when it was generated; a year from now when omitted.",
    )


class ConnectionCreatedResponse(BaseModel):
    connection_id: int = Field(description="The stored connection.", examples=[2])
    task_id: str | None = Field(description="Celery task of the first refresh, or null when the queue is down.")


def _frontend_redirect(**query: str) -> Redirect:
    # Every callback outcome ends the login attempt, so the state cookie goes with it.
    return Redirect(
        f"{settings.frontend_origin}{CONNECTIONS_PAGE}?{urlencode(query)}",
        status_code=302,
        cookies=[Cookie(key=OAUTH_STATE_COOKIE, value="", path=OAUTH_COOKIE_PATH, max_age=0)],
    )


@get(
    "/api/connections",
    operation_id="listConnections",
    summary="List broker connections",
    description=(
        "Returns every broker connection with its sync state. Token material is never included. "
        "Read-only, no side effects."
    ),
    responses={
        200: ResponseSpec(data_container=ConnectionsResponse, description="Broker connections and their state."),
        **standard_error_responses(),
    },
    tags=["Connections"],
    sync_to_thread=True,
)
def list_connections() -> ConnectionsResponse:
    return ConnectionsResponse(connections=connections.list_connections())


@get(
    "/api/connections/saxo/authorize",
    operation_id="startSaxoAuthorization",
    summary="Start the Saxo OAuth authorization",
    description=(
        "Creates a single-use state value and redirects the browser to SaxoBank's authorization page "
        "(authorization code grant). Side effect: stores the state for 15 minutes, server-side and in an "
        "HttpOnly cookie that the callback checks. Without SAXO_APP_KEY and SAXO_APP_SECRET it redirects "
        "back to the connections page with `error=not_configured`."
    ),
    status_code=302,
    tags=["Connections"],
    sync_to_thread=True,
)
def start_saxo_authorization() -> Redirect:
    try:
        auth.credentials()
    except auth.SaxoNotConfiguredError:
        return _frontend_redirect(error="not_configured")
    state = connections.create_oauth_state("saxo")
    cookie = Cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        path=OAUTH_COOKIE_PATH,
        max_age=15 * 60,
        httponly=True,
        # Lax still sends it on Saxo's top-level redirect back to the callback.
        samesite="lax",
        secure=settings.frontend_origin.startswith("https://"),
    )
    return Redirect(auth.build_authorize_url(state), status_code=302, cookies=[cookie])


@get(
    "/api/connections/saxo/callback",
    operation_id="completeSaxoAuthorization",
    summary="Complete the Saxo OAuth authorization",
    description=(
        "Redirect target registered in the Saxo app. Validates the state against the stored one and the "
        "browser's state cookie, exchanges the code for tokens, "
        "stores them encrypted, and redirects the browser back to the connections page with a "
        "`connected` parameter, or an `error` code: denied, missing_code, other_browser, invalid_state "
        "or exchange_failed."
    ),
    status_code=302,
    tags=["Connections"],
    sync_to_thread=True,
)
def complete_saxo_authorization(
    code: FromQuery[str | None] = None,
    # Litestar reserves the argument name ``state``, so the query parameter is renamed here.
    oauth_state: Annotated[
        str | None, QueryParameter(name="state", description="State issued by the authorize step.")
    ] = None,
    error: FromQuery[str | None] = None,
    state_cookie: Annotated[
        str | None, CookieParameter(name=OAUTH_STATE_COOKIE, description="State set by the authorize step.")
    ] = None,
) -> Redirect:
    # Error codes only: the connections page maps them to its own messages, so a crafted link
    # cannot make it display arbitrary text.
    if error:
        logger.warning("Saxo authorization returned an error: %.200s", error)
        return _frontend_redirect(error="denied")
    if not code or not oauth_state:
        return _frontend_redirect(error="missing_code")
    if state_cookie != oauth_state:
        return _frontend_redirect(error="other_browser")
    if connections.consume_oauth_state(oauth_state) is None:
        return _frontend_redirect(error="invalid_state")
    try:
        tokens = auth.exchange_code(code)
        connection_id = connections.save_connection("saxo", settings.saxo_environment, tokens)
    except Exception:
        logger.exception("Saxo token exchange failed")
        return _frontend_redirect(error="exchange_failed")
    _queue_refresh(connection_id)
    return _frontend_redirect(connected="saxo", connection_id=str(connection_id))


@post(
    "/api/connections/ibkr",
    operation_id="connectIbkr",
    summary="Connect Interactive Brokers through the Flex Web Service",
    description=(
        "Stores the Flex token encrypted together with the query id and the token's expiry, then queues the "
        "first refresh (statement pull, FX, ingest, prices, PnL rebuild). There is no OAuth: the token is "
        "generated in Client Portal under Performance & Reports, Flex Queries. Reconnecting with a new token "
        "replaces the stored one. Returns 400 when the token or query id is missing or malformed."
    ),
    status_code=201,
    responses={
        201: ResponseSpec(data_container=ConnectionCreatedResponse, description="Connection stored; refresh queued."),
        **standard_error_responses(),
    },
    tags=["Connections"],
    sync_to_thread=True,
)
def connect_ibkr(data: IbkrConnectRequest) -> ConnectionCreatedResponse:
    expires_at = data.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise ValidationException(detail="the token expiry is in the past")
    try:
        connection_id = ibkr.connect(data.token, data.query_id, expires_at)
    except ValueError as exc:
        raise ValidationException(detail=str(exc)) from exc
    return ConnectionCreatedResponse(connection_id=connection_id, task_id=_queue_refresh(connection_id))


def _queue_refresh(connection_id: int) -> str | None:
    """Queue the full refresh (sync, FX, ingest, prices, PnL rebuild); None when the task queue is down."""
    from app.tasks import refresh_connection

    try:
        return str(refresh_connection.delay(connection_id).id)
    except Exception:
        logger.exception("Could not queue the refresh for connection %s", connection_id)
        return None


@post(
    "/api/connections/{connection_id:int}/sync",
    operation_id="queueConnectionSync",
    summary="Queue a broker refresh",
    description=(
        "Queues a Celery task that pulls the broker's accounts, positions, balances and history, maps them "
        "into the ledger, then syncs prices and FX and rebuilds the PnL tables, so the dashboard reflects "
        "the latest broker data. Returns 404 for an unknown connection and 503 when the task queue is unavailable."
    ),
    status_code=202,
    responses={
        202: ResponseSpec(data_container=SyncQueuedResponse, description="Sync queued."),
        **standard_error_responses(),
    },
    tags=["Connections"],
    sync_to_thread=True,
)
def queue_connection_sync(connection_id: FromPath[int]) -> SyncQueuedResponse:
    if not any(connection.id == connection_id for connection in connections.list_connections()):
        raise NotFoundException(detail=f"connection {connection_id} does not exist")
    task_id = _queue_refresh(connection_id)
    if task_id is None:
        raise ServiceUnavailableException(detail="task queue unavailable")
    return SyncQueuedResponse(connection_id=connection_id, task_id=task_id)


routes = [list_connections, start_saxo_authorization, complete_saxo_authorization, connect_ibkr, queue_connection_sync]
