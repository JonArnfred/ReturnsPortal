"""Shared OpenAPI contract metadata for the application."""

from __future__ import annotations

from litestar.openapi import OpenAPIConfig
from litestar.openapi.datastructures import ResponseSpec
from litestar.openapi.spec import Example, Server, Tag

from app.config import settings
from app.models import ErrorResponse

API_VERSION = "1.0.0"


def standard_error_responses() -> dict[int, ResponseSpec]:
    """Return an independent response spec for each operation."""
    return {
        500: ResponseSpec(
            data_container=ErrorResponse,
            generate_examples=False,
            description="An unexpected server error using the standard API error envelope.",
            examples=[
                Example(
                    summary="Unexpected server error",
                    value={
                        "status_code": 500,
                        "error": "internal_server_error",
                        "detail": "An unexpected error occurred",
                        "request_id": "01JEXAMPLE1234567890",
                    },
                )
            ],
        )
    }


openapi_config = OpenAPIConfig(
    title=f"{settings.app_name} API",
    version=API_VERSION,
    summary="HTTP API contract for this application.",
    description=(
        "This OpenAPI document is the canonical contract for people, generated clients, "
        "integrations, and AI agents.\n\n"
        "## Contract conventions\n\n"
        "- Request and response bodies use JSON unless an operation says otherwise.\n"
        "- Treat each `operationId` as a stable machine-facing identifier.\n"
        "- Use the documented schemas and examples instead of inferring fields from prose.\n"
        "- Authentication, side effects, and error responses must be stated on each operation.\n"
        "- Framework-generated HTTP errors use the documented `ErrorResponse` envelope."
    ),
    servers=[Server(url="/", description="The origin that published this document")],
    tags=[
        Tag(name="Health", description="Process and required-dependency health probes."),
        Tag(name="Connections", description="Broker connections, OAuth flows, and sync triggers."),
        Tag(name="Investments", description="Ledger transactions, positions, and cash movements."),
        Tag(name="Data", description="Reference data feeds: daily prices and FX rates."),
        Tag(name="Reports", description="PnL attribution, unitized returns, reconciliation issues, rebuild."),
        Tag(name="Settings", description="Application settings changed from Setup, such as the reporting currency."),
    ],
    path="/api/schema",
)
