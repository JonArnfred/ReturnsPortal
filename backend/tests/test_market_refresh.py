from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from celery import chain
from litestar import Litestar
from litestar.testing import TestClient
from pytest import MonkeyPatch

import app.routes.connections as connections
import app.services.connection_service as connection_service
import app.services.fx_service as fx_service
import app.services.pnl_service as pnl_service
import app.services.price_service as price_service
import app.tasks as tasks
import scripts.refresh_market_data as refresh_market_data
from app.config import settings
from app.connectors.saxo import auth


@pytest.fixture
def services(monkeypatch: MonkeyPatch) -> Mock:
    services = Mock()
    report = SimpleNamespace(as_dict=lambda: {"done": True})
    monkeypatch.setattr(connection_service, "list_connections", lambda: [SimpleNamespace(id=1)])
    for name, module, attribute in (
        ("sync", tasks, "run_sync"),
        ("ingest", tasks, "ingest"),
        ("prices", price_service, "sync_prices"),
        ("fx", fx_service, "sync_fx"),
        ("pnl", pnl_service, "rebuild_all"),
    ):
        method = Mock(return_value={"done": True} if name == "pnl" else report)
        services.attach_mock(method, name)
        monkeypatch.setattr(module, attribute, method)
    return services


def test_startup_queues_fx_prices_and_pnl_in_order(monkeypatch: MonkeyPatch, services: Mock) -> None:
    queued = Mock()
    build_chain = Mock(return_value=queued)
    monkeypatch.setattr(refresh_market_data, "chain", build_chain)

    refresh_market_data.main()

    # Startup only queues work. Execute the real signatures locally to verify that
    # the reports are not passed as arguments and the rebuild follows both fetches.
    assert services.mock_calls == []
    queued.apply_async.assert_called_once_with()
    workflow = chain(*build_chain.call_args.args)
    workflow.apply(throw=True).get()
    assert services.mock_calls == [call.fx(), call.prices(1), call.pnl()]


def test_failed_fx_fetch_stops_startup_rebuild(monkeypatch: MonkeyPatch, services: Mock) -> None:
    build_chain = Mock()
    monkeypatch.setattr(refresh_market_data, "chain", build_chain)
    services.fx.side_effect = RuntimeError("FX unavailable")
    refresh_market_data.main()

    with pytest.raises(RuntimeError, match="FX unavailable"):
        chain(*build_chain.call_args.args).apply(throw=True).get()
    services.prices.assert_not_called()
    services.pnl.assert_not_called()


def test_failed_connection_does_not_block_other_prices(monkeypatch: MonkeyPatch, services: Mock) -> None:
    monkeypatch.setattr(connection_service, "list_connections", lambda: [SimpleNamespace(id=1), SimpleNamespace(id=2)])
    services.prices.side_effect = [RuntimeError("Saxo login expired"), SimpleNamespace(as_dict=lambda: {"bars": 5})]

    report = tasks.sync_prices.run()

    assert services.prices.call_args_list == [call(1), call(2)]
    assert report["connections"] == [{"connection_id": 1, "error": "Saxo login expired"}, {"bars": 5}]


def test_saxo_login_queues_refresh_after_saving_tokens(monkeypatch: MonkeyPatch, services: Mock) -> None:
    monkeypatch.setattr(connection_service, "consume_oauth_state", lambda state: "saxo")
    tokens = object()
    monkeypatch.setattr(auth, "exchange_code", lambda code: tokens)
    save = Mock(return_value=1)
    queued = Mock(return_value=SimpleNamespace(id="refresh-id"))
    events = Mock()
    events.attach_mock(save, "save")
    events.attach_mock(queued, "queue")
    monkeypatch.setattr(connection_service, "save_connection", save)
    monkeypatch.setattr(tasks.refresh_connection, "delay", queued)

    with TestClient(Litestar(route_handlers=[connections.complete_saxo_authorization])) as client:
        client.cookies.set(connections.OAUTH_STATE_COOKIE, "state")
        response = client.get("/api/connections/saxo/callback?code=code&state=state", follow_redirects=False)
    assert response.status_code == 302
    assert "connected=saxo" in response.headers["location"]
    assert f"{connections.OAUTH_STATE_COOKIE}=" in response.headers["set-cookie"]  # cleared
    assert events.mock_calls == [call.save("saxo", settings.saxo_environment, tokens), call.queue(1)]
    assert services.mock_calls == []

    tasks.refresh_connection.run(1)
    # FX before the ingest, which converts amounts into the reporting currency with it.
    assert services.mock_calls == [call.sync(1), call.fx(), call.ingest(1), call.prices(1), call.pnl()]


def test_unreachable_ecb_does_not_block_a_broker_refresh(services: Mock) -> None:
    services.fx.side_effect = RuntimeError("ECB unreachable")

    report = tasks.refresh_connection.run(1)

    assert services.mock_calls == [call.sync(1), call.fx(), call.ingest(1), call.prices(1), call.pnl()]
    assert report["fx"] == {"error": "RuntimeError: ECB unreachable"}


def test_invalid_saxo_login_does_not_queue_refresh(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(connection_service, "consume_oauth_state", lambda state: None)
    queued = Mock()
    monkeypatch.setattr(tasks.refresh_connection, "delay", queued)
    with TestClient(Litestar(route_handlers=[connections.complete_saxo_authorization])) as client:
        client.cookies.set(connections.OAUTH_STATE_COOKIE, "invalid")
        response = client.get("/api/connections/saxo/callback?code=code&state=invalid", follow_redirects=False)
    assert response.status_code == 302
    assert "error=invalid_state" in response.headers["location"]
    queued.assert_not_called()


def test_a_callback_from_another_browser_is_refused(monkeypatch: MonkeyPatch) -> None:
    consumed = Mock(return_value="saxo")
    monkeypatch.setattr(connection_service, "consume_oauth_state", consumed)
    with TestClient(Litestar(route_handlers=[connections.complete_saxo_authorization])) as client:
        response = client.get("/api/connections/saxo/callback?code=code&state=theirs", follow_redirects=False)
        assert "error=other_browser" in response.headers["location"]
        client.cookies.set(connections.OAUTH_STATE_COOKIE, "mine")
        response = client.get("/api/connections/saxo/callback?code=code&state=theirs", follow_redirects=False)
        assert "error=other_browser" in response.headers["location"]
    consumed.assert_not_called()


def test_authorize_without_a_saxo_app_goes_back_with_an_error(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "saxo_app_key", None)
    created = Mock()
    monkeypatch.setattr(connection_service, "create_oauth_state", created)
    with TestClient(Litestar(route_handlers=[connections.start_saxo_authorization])) as client:
        response = client.get("/api/connections/saxo/authorize", follow_redirects=False)
    assert response.status_code == 302 and "error=not_configured" in response.headers["location"]
    created.assert_not_called()


def test_authorize_sets_the_state_cookie(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "saxo_app_key", "app-key")
    monkeypatch.setattr(settings, "saxo_app_secret", "app-secret")
    monkeypatch.setattr(connection_service, "create_oauth_state", lambda broker: "fresh-state")
    monkeypatch.setattr(auth, "build_authorize_url", lambda state: f"https://saxo.test/authorize?state={state}")
    with TestClient(Litestar(route_handlers=[connections.start_saxo_authorization])) as client:
        response = client.get("/api/connections/saxo/authorize", follow_redirects=False)
    cookie = response.headers["set-cookie"]
    assert f"{connections.OAUTH_STATE_COOKIE}=fresh-state" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api/connections/saxo" in cookie
