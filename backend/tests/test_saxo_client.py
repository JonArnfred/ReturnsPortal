from __future__ import annotations

import httpx

from app.connectors.saxo.client import SaxoClient


def test_fetch_pages_follows_next_links_and_keeps_failures() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["Authorization"] == "Bearer tok"
        if request.url.path.endswith("/port/v1/accounts/me") and "page" not in str(request.url):
            return httpx.Response(
                200,
                json={"Data": [{"AccountKey": "A"}], "__next": "https://api.test/openapi/port/v1/accounts/me?page=2"},
            )
        if "page=2" in str(request.url):
            return httpx.Response(200, json={"Data": [{"AccountKey": "B"}]})
        return httpx.Response(404, json={"Message": "no"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = SaxoClient("tok", "https://api.test/openapi", http=http)
        pages = client.fetch_pages("port/v1/accounts/me", {"ClientKey": "c"})
        missing = client.fetch("cs/v1/reports/nothing/c")

    assert [page.status_code for page in pages] == [200, 200]
    assert [row["AccountKey"] for page in pages for row in page.data] == ["A", "B"]
    assert pages[0].params == {"ClientKey": "c"} and pages[1].params == {
        "__next": "https://api.test/openapi/port/v1/accounts/me?page=2"
    }
    assert calls[0] == "https://api.test/openapi/port/v1/accounts/me?ClientKey=c"
    assert not missing.ok and missing.payload == {"Message": "no"} and missing.data == []


def test_rate_limit_retries_with_retry_after() -> None:
    attempts = {"n": 0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"ClientKey": "ck"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = SaxoClient("tok", "https://api.test/openapi", http=http, sleep=slept.append)
        result = client.fetch("port/v1/clients/me")

    assert result.ok and result.payload == {"ClientKey": "ck"}
    assert slept == [1.0, 1.0]


def test_non_json_body_is_kept_as_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>gateway</html>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = SaxoClient("tok", "https://api.test/openapi", http=http).fetch("port/v1/clients/me")
    assert result.status_code == 502 and result.payload == {"_raw_text": "<html>gateway</html>"}


def test_a_401_renews_the_token_once_and_retries() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer stale":
            return httpx.Response(401, json={"Message": "token expired"})
        return httpx.Response(200, json={"Data": []})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SaxoClient("stale", "https://api.test/openapi", http=http, token_provider=lambda: "fresh")
    assert client.fetch("port/v1/balances").ok and client.access_token == "fresh"
    assert seen == ["Bearer stale", "Bearer fresh"]

    unchanged = SaxoClient("stale", "https://api.test/openapi", http=http, token_provider=lambda: "stale")
    assert unchanged.fetch("port/v1/balances").status_code == 401  # nothing newer to try


def test_paging_never_sends_the_token_outside_the_api() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"Data": [{"AccountKey": "A"}], "__next": "https://evil.test/openapi/x"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = SaxoClient("tok", "https://api.test/openapi", http=http)
        pages = client.fetch_pages("port/v1/accounts/me")

    assert len(pages) == 1 and calls == ["https://api.test/openapi/port/v1/accounts/me"]
