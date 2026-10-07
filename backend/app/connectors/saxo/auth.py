"""SaxoBank OpenAPI OAuth 2.0 authorization code grant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, Field

from app.config import settings

LIVE = {
    "authorize_url": "https://live.logonvalidation.net/authorize",
    "token_url": "https://live.logonvalidation.net/token",
    "api_base": "https://gateway.saxobank.com/openapi",
}
SIM = {
    "authorize_url": "https://sim.logonvalidation.net/authorize",
    "token_url": "https://sim.logonvalidation.net/token",
    "api_base": "https://gateway.saxobank.com/sim/openapi",
}


class SaxoNotConfiguredError(RuntimeError):
    pass


@dataclass(frozen=True)
class SaxoEndpoints:
    authorize_url: str
    token_url: str
    api_base: str


def endpoints(environment: str | None = None) -> SaxoEndpoints:
    env = environment or settings.saxo_environment
    table = LIVE if env == "live" else SIM
    return SaxoEndpoints(**table)


def credentials() -> tuple[str, str]:
    if not settings.saxo_app_key or not settings.saxo_app_secret:
        raise SaxoNotConfiguredError("SAXO_APP_KEY and SAXO_APP_SECRET must be set in backend/.env")
    return settings.saxo_app_key, settings.saxo_app_secret


class TokenSet(BaseModel):
    """Token response from the Saxo token endpoint, with absolute expiry times added."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(description="Access token lifetime in seconds.")
    refresh_token: str | None = None
    refresh_token_expires_in: int | None = None
    base_uri: str | None = None
    obtained_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def access_token_expires_at(self) -> datetime:
        return self.obtained_at + timedelta(seconds=self.expires_in)

    @property
    def refresh_token_expires_at(self) -> datetime | None:
        if self.refresh_token_expires_in is None:
            return None
        return self.obtained_at + timedelta(seconds=self.refresh_token_expires_in)


def build_authorize_url(state: str, environment: str | None = None) -> str:
    app_key, _ = credentials()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": app_key,
            "redirect_uri": settings.saxo_redirect_uri,
            "state": state,
        }
    )
    return f"{endpoints(environment).authorize_url}?{query}"


def _token_request(data: dict[str, str], environment: str | None, http: httpx.Client | None) -> TokenSet:
    app_key, app_secret = credentials()
    client = http or httpx.Client(timeout=30)
    try:
        response = client.post(endpoints(environment).token_url, data=data, auth=(app_key, app_secret))
    finally:
        if http is None:
            client.close()
    # Saxo answers a successful token grant with 201 Created.
    if not 200 <= response.status_code < 300:
        raise httpx.HTTPStatusError(
            f"Saxo token endpoint returned HTTP {response.status_code}: {response.text[:200]}",
            request=response.request,
            response=response,
        )
    return TokenSet.model_validate(response.json())


def exchange_code(code: str, environment: str | None = None, http: httpx.Client | None = None) -> TokenSet:
    return _token_request(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.saxo_redirect_uri},
        environment,
        http,
    )


def refresh_tokens(refresh_token: str, environment: str | None = None, http: httpx.Client | None = None) -> TokenSet:
    return _token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh_token, "redirect_uri": settings.saxo_redirect_uri},
        environment,
        http,
    )
