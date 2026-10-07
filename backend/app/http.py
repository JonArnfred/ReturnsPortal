"""HTTP boundary helpers: request IDs, structured access logs, and errors."""

from __future__ import annotations

import json
import logging
import re
from time import monotonic
from typing import Any
from uuid import uuid4

from litestar import Request, Response
from litestar.exceptions import HTTPException, PermissionDeniedException

from app.config import settings
from app.models import ErrorResponse

logger = logging.getLogger("returns-portal.http")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def request_id(scope: Any) -> str:
    state = scope.setdefault("state", {})
    value = state.get("request_id")
    if not isinstance(value, str):
        value = uuid4().hex
        state["request_id"] = value
    return value


def reject_cross_site_writes(request: Request[Any, Any, Any]) -> None:
    """The app has no login, so any page the user visits could otherwise send it a POST (a "simple"
    request needs no CORS preflight). Writes must come from the app's own pages, a configured CORS
    origin, or a non-browser client (no ``Origin``, no ``Sec-Fetch-Site``)."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin in settings.cors_allowed_origins:
        return
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        allowed = site in ("same-origin", "none")
    else:
        allowed = origin is None or origin == settings.frontend_origin
    if not allowed:
        raise PermissionDeniedException("Cross-site requests may not change anything")


def before_request(request: Request[Any, Any, Any]) -> None:
    supplied_request_id = request.headers.get("x-request-id", "")
    if REQUEST_ID_PATTERN.fullmatch(supplied_request_id):
        request.scope.setdefault("state", {})["request_id"] = supplied_request_id
    request_id(request.scope)
    request.scope["state"]["request_started_at"] = monotonic()
    reject_cross_site_writes(request)


def before_send(message: Any, scope: Any) -> None:
    if scope.get("type") != "http":
        return
    if message.get("type") == "http.response.start":
        headers = list(message.get("headers", []))
        headers.append((b"x-request-id", request_id(scope).encode("ascii")))
        message["headers"] = headers
        started = scope.get("state", {}).get("request_started_at", monotonic())
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id(scope),
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": message.get("status"),
                    "duration_ms": round((monotonic() - started) * 1000, 2),
                },
                separators=(",", ":"),
            )
        )


def handle_exception(request: Request[Any, Any, Any], exc: Exception) -> Response[ErrorResponse]:
    if isinstance(exc, HTTPException):
        status_code = exc.status_code
        detail = str(exc.detail)
    else:
        status_code = 500
        detail = str(exc) if settings.app_env == "development" else "An unexpected error occurred"
        logger.exception("Unhandled request error", exc_info=exc)

    known_error = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        409: "conflict",
        413: "payload_too_large",
        422: "validation_error",
        429: "rate_limited",
        503: "service_unavailable",
    }.get(status_code)
    error = known_error or ("client_error" if 400 <= status_code < 500 else "internal_server_error")
    return Response(
        ErrorResponse(status_code=status_code, error=error, detail=detail, request_id=request_id(request.scope)),
        status_code=status_code,
    )
