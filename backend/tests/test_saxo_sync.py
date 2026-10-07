from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from pytest import MonkeyPatch

from app.config import settings
from app.connectors.saxo import auth as saxo_auth
from app.connectors.saxo import sync
from app.connectors.saxo.client import SaxoClient
from app.services import connection_service as connections


class FakeStore:
    def __init__(self) -> None:
        self.payloads: list[tuple[str, dict[str, Any], int]] = []
        self.accounts: list[connections.BrokerAccount] = []
        self.details: dict[str, Any] = {}
        self.events: list[str] = []
        self.tokens: list[str] = []
        self.last_success_finished_at: datetime | None = None
        self.last_sync_error: str | None = None

    def install(
        self, monkeypatch: MonkeyPatch, expires_in: timedelta = timedelta(hours=1), client_key: str | None = None
    ) -> None:
        secrets = connections.ConnectionSecrets(
            id=7,
            broker="saxo",
            environment="live",
            client_key=client_key,
            access_token="old-token",
            refresh_token="refresh",
            access_token_expires_at=datetime.now(UTC) + expires_in,
            refresh_token_expires_at=None,
        )
        monkeypatch.setattr(connections, "load_secrets", lambda connection_id: secrets if connection_id == 7 else None)
        monkeypatch.setattr(connections, "get_connection", lambda connection_id: self._status(connection_id))
        monkeypatch.setattr(
            connections,
            "record_raw_payload",
            lambda cid, ep, params, status, payload: self.payloads.append((ep, params, status)),
        )
        monkeypatch.setattr(connections, "upsert_account_records", self._upsert_accounts)
        monkeypatch.setattr(connections, "update_client_details", lambda cid, **kw: self.details.update(kw))
        monkeypatch.setattr(connections, "mark_sync_started", lambda cid: self.events.append("started"))
        monkeypatch.setattr(
            connections, "mark_sync_finished", lambda cid, error: self.events.append(f"finished:{error}")
        )
        monkeypatch.setattr(connections, "store_tokens", lambda cid, tokens: self.tokens.append(tokens.access_token))

    def _status(self, connection_id: int) -> connections.ConnectionStatus | None:
        if connection_id != 7:
            return None
        return connections.ConnectionStatus(
            id=7,
            broker="saxo",
            environment="live",
            client_key=None,
            client_name=None,
            base_currency=None,
            status="connected",
            account_count=0,
            access_token_expires_at=datetime.now(UTC),
            refresh_token_expires_at=None,
            last_sync_started_at=self.last_success_finished_at,
            last_sync_finished_at=self.last_success_finished_at,
            last_sync_error=self.last_sync_error,
            last_success_finished_at=self.last_success_finished_at,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def _upsert_accounts(self, cid: int, rows: list[connections.BrokerAccount]) -> int:
        self.accounts.extend(rows)
        return len(rows)


def saxo_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/port/v1/clients/me"):
        return httpx.Response(200, json={"ClientKey": "CK", "Name": "Tester", "DefaultCurrency": "DKK"})
    if path.endswith("/port/v1/accounts/me"):
        return httpx.Response(
            200, json={"Data": [{"AccountKey": "AK1", "Currency": "DKK"}, {"AccountKey": "AK2", "Currency": "USD"}]}
        )
    if "/cs/v1/reports/bookings/" in path:
        return httpx.Response(404, json={"Message": "Not found"})
    if "/cs/v1/reports/trades/" in path:
        return httpx.Response(
            200, json={"Data": [{"row": request.url.params["FromDate"], "Uic": 207, "AssetType": "Stock"}]}
        )
    if path.endswith("/port/v1/orders/me"):
        return httpx.Response(
            200, json={"Data": [{"OrderId": "O-1", "Uic": 999, "AssetType": "Stock", "Status": "Working"}]}
        )
    if path.endswith("/cs/v1/audit/orderactivities"):
        return httpx.Response(
            200, json={"Data": [{"OrderId": "O-2", "Uic": 555, "AssetType": "Etf", "Status": "FinalFill"}]}
        )
    if path.endswith("/port/v1/positions"):
        return httpx.Response(200, json={"Data": [{"PositionBase": {"Uic": 1000002, "AssetType": "Stock"}}]})
    if path.endswith("/ref/v1/instruments/details"):
        return httpx.Response(
            200,
            json={
                "Data": [
                    {"Uic": int(u), "AssetType": request.url.params["AssetTypes"]}
                    for u in request.url.params["Uics"].split(",")
                ]
            },
        )
    return httpx.Response(200, json={"Data": []})


def test_capture_stores_every_response_and_skips_unavailable_reports(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch)
    monkeypatch.setattr(settings, "saxo_history_start", "2024-06-01")

    with httpx.Client(transport=httpx.MockTransport(saxo_handler)) as http:
        client = SaxoClient("old-token", "https://api.test/openapi", http=http)
        report = sync.run_sync(7, client=client, today=date(2026, 3, 1))

    endpoints = [endpoint for endpoint, _, _ in store.payloads]
    assert endpoints[:2] == ["port/v1/clients/me", "port/v1/accounts/me"]
    assert endpoints.count("port/v1/balances") == 3  # client-level plus one per account
    # Three yearly windows (2024, 2025, 2026) for each available report; the 404 report stops after one.
    assert endpoints.count("cs/v1/reports/trades/CK") == 3
    assert endpoints.count("cs/v1/reports/bookings/CK") == 1
    assert "port/v1/closedpositions" not in endpoints
    assert endpoints.count("ref/v1/exchanges") == 1
    assert endpoints.count("port/v1/orders/me") == 1
    assert endpoints.count("cs/v1/audit/orderactivities") == 3  # same yearly windows as the reports
    audit = [params for endpoint, params, _ in store.payloads if endpoint == "cs/v1/audit/orderactivities"]
    assert audit[0] == {"ClientKey": "CK", "FromDateTime": "2024-06-01T00:00:00Z", "ToDateTime": "2024-12-31T23:59:59Z"}
    details = [params for endpoint, params, _ in store.payloads if endpoint == "ref/v1/instruments/details"]
    assert details == [{"Uics": "207,999,1000002", "AssetTypes": "Stock"}, {"Uics": "555", "AssetTypes": "Etf"}]
    windows = [params for endpoint, params, _ in store.payloads if endpoint == "cs/v1/reports/trades/CK"]
    assert windows[0] == {"FromDate": "2024-06-01", "ToDate": "2024-12-31"}
    assert windows[-1] == {"FromDate": "2026-01-01", "ToDate": "2026-03-01"}

    assert store.details == {"client_key": "CK", "client_name": "Tester", "base_currency": "DKK"}
    assert [(account.account_key, account.currency) for account in store.accounts] == [("AK1", "DKK"), ("AK2", "USD")]
    assert store.events == ["started", "finished:None"]
    assert report.accounts == 2 and report.requests == len(store.payloads) == report.stored_payloads
    assert report.failures == [
        "cs/v1/reports/bookings/CK {'FromDate': '2024-06-01', 'ToDate': '2024-12-31'} -> HTTP 404"
    ]
    assert store.tokens == []


def test_a_login_for_another_client_stores_nothing(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch, client_key="OTHER")

    with (
        httpx.Client(transport=httpx.MockTransport(saxo_handler)) as http,
        pytest.raises(connections.ClientMismatchError),
    ):
        sync.run_sync(7, client=SaxoClient("old-token", "https://api.test/openapi", http=http), today=date(2026, 3, 1))

    assert store.payloads == [] and store.details == {}
    assert store.events[0] == "started" and store.events[1].startswith("finished:this saxo connection belongs to")


def test_later_syncs_pull_only_the_days_since_the_last_good_one(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch)
    store.last_success_finished_at = datetime(2026, 2, 27, 5, 0, tzinfo=UTC)
    monkeypatch.setattr(settings, "saxo_history_start", "2024-06-01")

    def windows(**kwargs: Any) -> list[dict[str, Any]]:
        store.payloads.clear()
        with httpx.Client(transport=httpx.MockTransport(saxo_handler)) as http:
            client = SaxoClient("old-token", "https://api.test/openapi", http=http)
            sync.run_sync(7, client=client, today=date(2026, 3, 1), **kwargs)
        return [params for endpoint, params, _ in store.payloads if endpoint == "cs/v1/reports/trades/CK"]

    assert windows() == [{"FromDate": "2026-02-13", "ToDate": "2026-03-01"}]
    assert len(windows(full=True)) == 3
    store.last_sync_error = "HTTP 503"  # a failed sync since then does not restart from the beginning
    assert windows() == [{"FromDate": "2026-02-13", "ToDate": "2026-03-01"}]


def test_expired_token_is_refreshed_before_sync(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch, expires_in=timedelta(seconds=30))
    refreshed: list[str] = []

    def fake_refresh(refresh_token: str, environment: str | None = None, http: Any = None) -> Any:
        refreshed.append(refresh_token)
        from app.connectors.saxo.auth import TokenSet

        return TokenSet(access_token="fresh", expires_in=1200, refresh_token="refresh-2")

    monkeypatch.setattr(saxo_auth, "refresh_tokens", fake_refresh)
    created: list[SaxoClient] = []

    def fake_client(token: str, api_base: str, **kwargs: Any) -> SaxoClient:
        http = httpx.Client(transport=httpx.MockTransport(saxo_handler))
        client = SaxoClient(token, api_base, http=http, **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(sync, "SaxoClient", fake_client)
    monkeypatch.setattr(settings, "saxo_history_start", "2026-01-01")
    sync.run_sync(7, today=date(2026, 1, 15))
    assert refreshed == ["refresh"] and store.tokens == ["fresh"] and created[0].access_token == "fresh"


def test_failure_is_recorded_and_reraised(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch)

    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"Message": "expired"})

    with httpx.Client(transport=httpx.MockTransport(failing)) as http:
        client = SaxoClient("old-token", "https://api.test/openapi", http=http)
        with pytest.raises(RuntimeError, match="clients/me failed with HTTP 401"):
            sync.run_sync(7, client=client)
    assert store.events[0] == "started" and store.events[1].startswith("finished:port/v1/clients/me failed")
    assert store.payloads == [("port/v1/clients/me", {}, 401)]


def test_year_windows() -> None:
    assert sync._year_windows(date(2025, 11, 20), date(2026, 2, 3)) == [
        (date(2025, 11, 20), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 2, 3)),
    ]


def test_keep_token_alive_refreshes_only_when_due_and_marks_rejections(monkeypatch: MonkeyPatch) -> None:
    from app.connectors.saxo.auth import TokenSet

    store = FakeStore()
    store.install(monkeypatch, expires_in=timedelta(hours=2))
    assert sync.keep_token_alive(7) == "fresh"

    store.install(monkeypatch, expires_in=timedelta(minutes=10))
    monkeypatch.setattr(
        saxo_auth,
        "refresh_tokens",
        lambda token, env=None, http=None: TokenSet(access_token="fresh", expires_in=1200, refresh_token="r2"),
    )
    assert sync.keep_token_alive(7) == "refreshed" and store.tokens == ["fresh"]

    expired: list[tuple[int, str]] = []
    monkeypatch.setattr(connections, "mark_token_expired", lambda cid, error: expired.append((cid, error)))

    def rejected(token: str, env: Any = None, http: Any = None) -> Any:
        response = httpx.Response(401, request=httpx.Request("POST", "https://sim.logonvalidation.net/token"))
        raise httpx.HTTPStatusError("HTTP 401", request=response.request, response=response)

    monkeypatch.setattr(saxo_auth, "refresh_tokens", rejected)
    assert sync.keep_token_alive(7) == "expired" and expired[0][0] == 7 and "rejected" in expired[0][1]


def test_a_fill_counts_as_booked_when_its_order_has_a_trade_within_a_day() -> None:
    from datetime import date

    from app.connectors.saxo.ingest import is_booked

    booked = {("9000000002", date(2026, 9, 22)), ("111", date(2026, 9, 1))}
    assert is_booked("9000000002", date(2026, 9, 21), booked)
    assert not is_booked("9000000002", date(2026, 9, 24), booked)
    assert not is_booked("999", date(2026, 9, 21), booked)
