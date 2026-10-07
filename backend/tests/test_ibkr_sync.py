from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from pytest import MonkeyPatch

from app.config import settings
from app.connectors.ibkr import connect, sync
from app.connectors.ibkr.client import FlexClient
from app.services import connection_service as connections

STATUS_OK = "<FlexStatementResponse><Status>Success</Status><ReferenceCode>REF</ReferenceCode></FlexStatementResponse>"


def statement_xml(from_date: str, to_date: str, *, opened: str = "2025-10-01", trades: int = 1) -> str:
    trade_rows = "".join(
        f'<Trade tradeID="{index}" accountId="U1" currency="EUR" assetCategory="STK" conid="7" quantity="1" tradeDate="{to_date}"/>'  # noqa: E501
        for index in range(trades)
    )
    return f"""<FlexQueryResponse queryName="q" type="AF"><FlexStatements count="1">
    <FlexStatement accountId="U1" fromDate="{from_date}" toDate="{to_date}" period="x"
                   whenGenerated="2026-09-21;06:00:00">
      <AccountInformation accountId="U1" currency="EUR" name="Tester" accountType="Individual"
                          dateOpened="{opened}" street="Somewhere"/>
      <EquitySummaryInBase>
        <EquitySummaryByReportDateInBase accountId="U1" currency="EUR" reportDate="{to_date}" total="10"/>
      </EquitySummaryInBase>
      <Trades>{trade_rows}</Trades>
      <OpenPositions/>
    </FlexStatement></FlexStatements></FlexQueryResponse>"""


class FakeStore:
    def __init__(self) -> None:
        self.payloads: list[tuple[str, dict[str, Any], int, Any]] = []
        self.accounts: list[connections.BrokerAccount] = []
        self.details: dict[str, Any] = {}
        self.events: list[str] = []

    def install(
        self, monkeypatch: MonkeyPatch, *, last_success: datetime | None, expires_in: timedelta = timedelta(days=30)
    ) -> None:
        secrets = connections.ConnectionSecrets(
            id=9,
            broker="ibkr",
            environment="live",
            client_key=None,
            access_token="tok",
            refresh_token=None,
            access_token_expires_at=datetime.now(UTC) + expires_in,
            refresh_token_expires_at=None,
            query_id="1234567",
        )
        status = connections.ConnectionStatus(
            id=9,
            broker="ibkr",
            environment="live",
            client_key=None,
            client_name=None,
            base_currency=None,
            status="connected",
            account_count=0,
            access_token_expires_at=secrets.access_token_expires_at,
            refresh_token_expires_at=None,
            last_sync_started_at=None,
            last_sync_finished_at=last_success,
            last_sync_error=None,
            last_success_finished_at=last_success,
            created_at=datetime.now(UTC),
        )
        monkeypatch.setattr(connections, "load_secrets", lambda connection_id: secrets if connection_id == 9 else None)
        monkeypatch.setattr(connections, "get_connection", lambda connection_id: status if connection_id == 9 else None)
        monkeypatch.setattr(
            connections,
            "record_raw_payload",
            lambda cid, endpoint, params, code, payload: self.payloads.append((endpoint, params, code, payload)),
        )
        monkeypatch.setattr(connections, "upsert_account_records", self._upsert_accounts)
        monkeypatch.setattr(connections, "update_client_details", lambda cid, **kw: self.details.update(kw))
        monkeypatch.setattr(connections, "mark_sync_started", lambda cid: self.events.append("started"))
        monkeypatch.setattr(
            connections, "mark_sync_finished", lambda cid, error: self.events.append(f"finished:{error}")
        )
        monkeypatch.setattr(
            connections, "mark_token_expired", lambda cid, error: self.events.append(f"expired:{error}")
        )

    def _upsert_accounts(self, cid: int, rows: list[connections.BrokerAccount]) -> int:
        self.accounts.extend(rows)
        return len(rows)

    def endpoints(self) -> list[str]:
        return [endpoint for endpoint, _, _, _ in self.payloads]


def make_client(handler) -> FlexClient:  # type: ignore[no-untyped-def]
    return FlexClient("tok", http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda seconds: None)


def statement_handler(requests: list[dict[str, str]], *, opened: str = "2025-10-01"):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if request.url.path.endswith("SendRequest"):
            requests.append({key: value for key, value in params.items() if key != "t"})
            return httpx.Response(200, text=STATUS_OK)
        window = requests[-1]
        if "p" in window:
            to_date = date(2026, 9, 18)
            from_date = to_date - timedelta(days=int(window["p"]) - 1)
        else:
            from_date = datetime.strptime(window["fd"], "%Y%m%d").date()
            to_date = datetime.strptime(window["td"], "%Y%m%d").date()
        return httpx.Response(200, text=statement_xml(from_date.isoformat(), to_date.isoformat(), opened=opened))

    return handler


def test_first_sync_bootstraps_then_pulls_since_the_account_opened(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch, last_success=None)
    monkeypatch.setattr(settings, "ibkr_history_start", None)
    requests: list[dict[str, str]] = []
    report = sync.run_sync(9, client=make_client(statement_handler(requests)), today=date(2026, 9, 21))

    assert [window.get("p") for window in requests] == [
        str(sync.BOOTSTRAP_DAYS),
        str((date(2026, 9, 21) - date(2025, 10, 1)).days + 1),
    ]
    assert report.requests == 2 and not report.failures
    assert store.events == ["started", "finished:None"]
    assert store.details == {"client_key": "U1", "client_name": "Tester", "base_currency": "EUR"}
    assert store.accounts[0].account_key == "U1" and store.accounts[0].currency == "EUR"
    assert "street" not in store.accounts[0].raw
    json.dumps(store.accounts[0].raw)  # what goes into the jsonb column must be plain JSON
    json.dumps([payload for _, _, _, payload in store.payloads])
    endpoints = store.endpoints()
    assert endpoints.count("flex/statement/Trades") == 2 and "flex/statement/AccountInformation" in endpoints
    account_payload = next(
        payload for endpoint, _, _, payload in store.payloads if endpoint.endswith("AccountInformation")
    )
    assert "street" not in account_payload["rows"][0] and account_payload["rows"][0]["dateOpened"] == "2025-10-01"
    trades_params = next(params for endpoint, params, _, _ in store.payloads if endpoint.endswith("Trades"))
    assert trades_params["accountId"] == "U1" and "t" not in trades_params


def test_old_accounts_are_pulled_in_year_windows_ending_on_a_weekday(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch, last_success=None)
    monkeypatch.setattr(settings, "ibkr_history_start", None)
    requests: list[dict[str, str]] = []
    sync.run_sync(9, client=make_client(statement_handler(requests, opened="2024-03-01")), today=date(2026, 9, 21))
    windows = [(window["fd"], window["td"]) for window in requests if "fd" in window]
    assert windows == [("20240301", "20250228"), ("20250301", "20260228"), ("20260301", "20260918")]


def test_incremental_sync_pulls_the_days_since_the_last_success_with_overlap(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch, last_success=datetime(2026, 9, 10, 4, 30, tzinfo=UTC))
    requests: list[dict[str, str]] = []
    sync.run_sync(9, client=make_client(statement_handler(requests)), today=date(2026, 9, 21))
    assert requests == [{"q": "1234567", "v": "3", "p": "14"}]
    assert sync.incremental_days(datetime(2026, 9, 20, tzinfo=UTC), date(2026, 9, 21)) == sync.MIN_INCREMENTAL_DAYS
    assert sync.incremental_days(datetime(2020, 1, 1, tzinfo=UTC), date(2026, 9, 21)) == sync.MAX_WINDOW_DAYS


def test_full_sync_pulls_the_whole_history_again(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch, last_success=datetime(2026, 9, 10, 4, 30, tzinfo=UTC))
    monkeypatch.setattr(settings, "ibkr_history_start", None)
    requests: list[dict[str, str]] = []
    sync.run_sync(9, client=make_client(statement_handler(requests)), today=date(2026, 9, 21), full=True)
    assert [window.get("p") for window in requests] == [
        str(sync.BOOTSTRAP_DAYS),
        str((date(2026, 9, 21) - date(2025, 10, 1)).days + 1),
    ]


def test_rejected_token_marks_the_connection_expired(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch, last_success=datetime(2026, 9, 10, tzinfo=UTC))
    error = "<FlexStatementResponse><Status>Fail</Status><ErrorCode>1012</ErrorCode><ErrorMessage>Token has expired.</ErrorMessage></FlexStatementResponse>"  # noqa: E501
    client = make_client(lambda request: httpx.Response(200, text=error))
    with pytest.raises(RuntimeError, match="1012"):
        sync.run_sync(9, client=client, today=date(2026, 9, 21))
    assert (
        store.events[0] == "started"
        and store.events[1].startswith("expired:")
        and store.events[2].startswith("finished:Flex token")
    )
    assert store.endpoints() == [sync.ERROR_ENDPOINT] and store.payloads[0][2] == 502


def test_windows_and_weekdays() -> None:
    assert sync.windows(date(2024, 1, 1), date(2024, 12, 31)) == [
        (date(2024, 1, 1), date(2024, 12, 30)),
        (date(2024, 12, 31), date(2024, 12, 31)),
    ]
    assert sync.last_weekday_before(date(2026, 9, 21)) == date(2026, 9, 18)  # Monday -> Friday
    assert sync.last_weekday_before(date(2026, 9, 23)) == date(2026, 9, 22)


def test_keep_token_alive_marks_expiry(monkeypatch: MonkeyPatch) -> None:
    store = FakeStore()
    store.install(monkeypatch, last_success=None, expires_in=timedelta(days=-1))
    assert connect.keep_token_alive(9) == "expired"
    assert store.events == ["expired:Flex token expired; generate a new one in Client Portal"]
    store.install(monkeypatch, last_success=None, expires_in=timedelta(days=10))
    assert connect.keep_token_alive(9) == "fresh"


def test_connect_validates_and_stores(monkeypatch: MonkeyPatch) -> None:
    saved: dict[str, Any] = {}

    def save(broker: str, environment: str, tokens: Any, *, query_id: str | None = None) -> int:
        saved.update(
            broker=broker,
            environment=environment,
            token=tokens.access_token,
            expires=tokens.access_token_expires_at,
            query_id=query_id,
        )
        return 5

    monkeypatch.setattr(connections, "save_connection", save)
    assert connect.connect(" abc12345 ", "1234567 ") == 5
    assert saved["broker"] == "ibkr" and saved["token"] == "abc12345" and saved["query_id"] == "1234567"
    assert saved["expires"] - datetime.now(UTC) > timedelta(days=364)
    with pytest.raises(ValueError):
        connect.connect("abc", "not-a-number")
    with pytest.raises(ValueError):
        connect.connect("", "123")
