"""Shared API response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Stable error envelope returned by the API."""

    status_code: int = Field(description="HTTP status code.", examples=[400])
    error: str = Field(description="Stable machine-readable error category.", examples=["bad_request"])
    detail: str = Field(
        description="Human-readable explanation safe to show to a caller.",
        examples=["The request could not be processed."],
    )
    request_id: str = Field(
        description="Identifier for correlating the response with server logs.",
        examples=["01JEXAMPLE1234567890"],
    )


class StatusResponse(BaseModel):
    status: str = Field(description="Current service state.", examples=["ok"])
