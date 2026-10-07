"""Health-check routes."""

from __future__ import annotations

from litestar import Response, get
from litestar.openapi.datastructures import ResponseSpec

from app.models import StatusResponse
from app.openapi import standard_error_responses
from app.services.health_service import ReadinessReport, check_readiness


@get(
    "/api/health/live",
    operation_id="getLiveness",
    summary="Check whether the API process is alive",
    description=(
        "A dependency-free probe for process supervisors. This operation is public, read-only, and has no side effects."
    ),
    responses={
        200: ResponseSpec(data_container=StatusResponse, description="The API process can accept requests."),
        **standard_error_responses(),
    },
    tags=["Health"],
    sync_to_thread=False,
)
def live() -> StatusResponse:
    return StatusResponse(status="ok")


@get(
    "/api/health/ready",
    operation_id="getReadiness",
    summary="Check required service dependencies",
    description=(
        "Checks Postgres and Redis with short timeouts. Returns HTTP 200 when both dependencies respond "
        "and HTTP 503 otherwise. This public, read-only operation has no side effects."
    ),
    responses={
        200: ResponseSpec(data_container=ReadinessReport, description="All required dependencies are ready."),
        503: ResponseSpec(
            data_container=ReadinessReport, description="At least one required dependency is unavailable."
        ),
        **standard_error_responses(),
    },
    tags=["Health"],
    sync_to_thread=True,
)
def ready() -> Response[ReadinessReport]:
    report = check_readiness()
    return Response(report, status_code=200 if report.status == "ready" else 503)
