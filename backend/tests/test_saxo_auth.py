from __future__ import annotations

import base64
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pytest import MonkeyPatch

from app.config import settings
from app.connectors.saxo import auth


@pytest.fixture(autouse=True)
def saxo_settings(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "saxo_app_key", "app-key")
    monkeypatch.setattr(settings, "saxo_app_secret", "app-secret")
    monkeypatch.setattr(settings, "saxo_environment", "live")
    monkeypatch.setattr(settings, "saxo_redirect_uri", "http://localhost:25183/api/connections/saxo/callback")


def test_authorize_url_uses_code_grant_and_state() -> None:
    url = urlparse(auth.build_authorize_url("state-123"))
    assert url.scheme == "https" and url.netloc == "live.logonvalidation.net" and url.path == "/authorize"
    query = parse_qs(url.query)
    assert query == {
        "response_type": ["code"],
        "client_id": ["app-key"],
        "redirect_uri": ["http://localhost:25183/api/connections/saxo/callback"],
        "state": ["state-123"],
    }
    assert "sim.logonvalidation.net" in auth.build_authorize_url("s", environment="sim")


def test_missing_credentials_raise(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "saxo_app_key", None)
    with pytest.raises(auth.SaxoNotConfiguredError):
        auth.build_authorize_url("s")


def test_exchange_code_posts_form_with_basic_auth() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["form"] = parse_qs(request.content.decode())
        return httpx.Response(
            201,
            json={
                "access_token": "acc",
                "token_type": "Bearer",
                "expires_in": 1200,
                "refresh_token": "ref",
                "refresh_token_expires_in": 3600,
                "base_uri": None,
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        tokens = auth.exchange_code("the-code", http=http)

    assert seen["url"] == "https://live.logonvalidation.net/token"
    assert seen["auth"] == "Basic " + base64.b64encode(b"app-key:app-secret").decode()
    assert seen["form"] == {
        "grant_type": ["authorization_code"],
        "code": ["the-code"],
        "redirect_uri": ["http://localhost:25183/api/connections/saxo/callback"],
    }
    assert tokens.access_token == "acc" and tokens.refresh_token == "ref"
    assert (tokens.access_token_expires_at - tokens.obtained_at).total_seconds() == 1200
    assert tokens.refresh_token_expires_at is not None
    assert tokens.obtained_at.tzinfo is UTC or tokens.obtained_at.utcoffset() == datetime.now(UTC).utcoffset()


def test_refresh_and_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        if form.get("grant_type") == ["refresh_token"] and form.get("refresh_token") == ["old"]:
            return httpx.Response(200, json={"access_token": "new", "expires_in": 60})
        return httpx.Response(401, text="invalid_grant")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        assert auth.refresh_tokens("old", http=http).access_token == "new"
        with pytest.raises(httpx.HTTPStatusError):
            auth.refresh_tokens("bad", http=http)
