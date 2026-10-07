from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.connectors.ibkr.client import FlexClient, FlexHttpError, window_params

STATUS_OK = (
    "<FlexStatementResponse timestamp='x'><Status>Success</Status><ReferenceCode>REF1</ReferenceCode>"
    "<Url>https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement</Url></FlexStatementResponse>"
)
STATEMENT = "<FlexQueryResponse queryName='q' type='AF'><FlexStatements count='1'></FlexStatements></FlexQueryResponse>"


def error(code: str, message: str) -> str:
    return (
        f"<FlexStatementResponse timestamp='x'><Status>Warn</Status><ErrorCode>{code}</ErrorCode>"
        f"<ErrorMessage>{message}</ErrorMessage></FlexStatementResponse>"
    )


def make_client(handler) -> tuple[FlexClient, list[float]]:  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return FlexClient("secret-token", http=http, sleep=sleeps.append), sleeps


def test_window_params_period_or_dates() -> None:
    assert window_params("123", period_days=30) == {"q": "123", "v": "3", "p": "30"}
    assert window_params("123", from_date=date(2026, 1, 5), to_date=date(2026, 3, 1)) == {
        "q": "123",
        "v": "3",
        "fd": "20260105",
        "td": "20260301",
    }


def test_polls_until_the_statement_is_generated() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("SendRequest"):
            return httpx.Response(200, text=STATUS_OK)
        assert request.url.params["q"] == "REF1"
        if len(calls) < 4:
            return httpx.Response(
                200, text=error("1019", "Statement generation in progress. Please try again shortly.")
            )
        return httpx.Response(200, text=STATEMENT)

    client, sleeps = make_client(handler)
    result = client.fetch_statement(window_params("123", period_days=7))
    assert result.ok and result.reference_code == "REF1" and "FlexQueryResponse" in result.text
    assert result.params == {"q": "123", "v": "3", "p": "7"}  # the token is never part of the recorded params
    assert all(request.url.params["t"] == "secret-token" for request in calls)
    assert all(request.headers["User-Agent"].startswith("returns-portal") for request in calls)
    assert sleeps == [client.poll_seconds, client.poll_seconds]


def test_throttling_waits_longer_and_credential_errors_are_flagged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("SendRequest"):
            return httpx.Response(200, text=STATUS_OK)
        if not handler.throttled:  # type: ignore[attr-defined]
            handler.throttled = True  # type: ignore[attr-defined]
            return httpx.Response(200, text=error("1018", "Too many requests have been made from this token."))
        return httpx.Response(200, text=error("1012", "Token has expired."))

    handler.throttled = False  # type: ignore[attr-defined]
    client, sleeps = make_client(handler)
    result = client.fetch_statement(window_params("123", period_days=7))
    assert not result.ok and result.error_code == "1012" and result.credential_problem
    assert sleeps == [15.0]


def test_a_throttled_send_request_is_retried() -> None:
    sends: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("SendRequest"):
            sends.append(1)
            if len(sends) < 3:
                return httpx.Response(200, text=error("1018", "Too many requests have been made from this token."))
            return httpx.Response(200, text=STATUS_OK)
        return httpx.Response(200, text=STATEMENT)

    client, sleeps = make_client(handler)
    assert client.fetch_statement(window_params("123", period_days=7)).ok
    assert len(sends) == 3 and sleeps == [60.0, 60.0]

    always = make_client(lambda request: httpx.Response(200, text=error("1018", "Too many requests.")))[0]
    assert always.fetch_statement(window_params("123", period_days=7)).error_code == "1018"


def test_send_request_failure_returns_the_error() -> None:
    client, _ = make_client(lambda request: httpx.Response(200, text=error("1003", "Statement is not available.")))
    result = client.fetch_statement(window_params("123", from_date=date(2026, 9, 1), to_date=date(2026, 9, 19)))
    assert result.error_code == "1003" and result.reference_code is None and not result.credential_problem


def test_http_errors_never_carry_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    client, _ = make_client(handler)
    with pytest.raises(FlexHttpError) as raised:
        client.fetch_statement(window_params("123", period_days=30))
    assert "secret-token" not in str(raised.value) and "503" in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    client, _ = make_client(broken)
    with pytest.raises(FlexHttpError) as raised:
        client.fetch_statement(window_params("123", period_days=30))
    assert "secret-token" not in str(raised.value) and "ConnectError" in str(raised.value)
