from litestar.testing import TestClient

from app.api import app


def test_request_id_is_echoed() -> None:
    with TestClient(app=app) as client:
        response = client.get("/api/health/live", headers={"host": "localhost", "x-request-id": "test-request-123"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"] == "test-request-123"


def test_openapi_document_is_complete_and_machine_stable() -> None:
    schema = app.openapi_schema.to_schema()
    operation = schema["paths"]["/api/settings/reporting-currency"]["put"]

    assert schema["openapi"] == "3.1.0"
    assert schema["info"]["version"] == "1.0.0"
    assert schema["servers"] == [{"url": "/", "description": "The origin that published this document"}]
    assert operation["operationId"] == "setReportingCurrency"
    assert operation["tags"] == ["Settings"]
    assert operation["responses"]["500"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert set(schema["components"]["schemas"]["ErrorResponse"]["required"]) == {
        "status_code",
        "error",
        "detail",
        "request_id",
    }
    operation_ids = [op["operationId"] for path in schema["paths"].values() for op in path.values()]
    assert len(operation_ids) == len(set(operation_ids))


def test_public_schema_lists_every_endpoint() -> None:
    schema = app.openapi_schema.to_schema()

    assert set(schema["paths"]) == {
        "/api/health/live",
        "/api/health/ready",
        "/api/connections",
        "/api/connections/saxo/authorize",
        "/api/connections/saxo/callback",
        "/api/connections/ibkr",
        "/api/connections/{connection_id}/sync",
        "/api/ledger/transactions",
        "/api/ledger/cash-movements",
        "/api/positions",
        "/api/positions/{position_id}",
        "/api/portfolios",
        "/api/portfolios/{portfolio_id}",
        "/api/orders",
        "/api/preferences",
        "/api/preferences/{key}",
        "/api/prices",
        "/api/prices/status",
        "/api/fx",
        "/api/fx/status",
        "/api/reports/dashboard",
        "/api/reports/pnl",
        "/api/reports/portfolio-days",
        "/api/reports/rebuild",
        "/api/reconciliation/issues",
        "/api/settings/reporting-currency",
    }


def test_schema_is_served_below_api_prefix() -> None:
    with TestClient(app=app) as client:
        response = client.get("/api/schema/openapi.json", headers={"host": "localhost"})

    assert response.status_code == 200
    assert response.json()["paths"]["/api/health/live"]["get"]["operationId"] == "getLiveness"


def test_api_errors_use_the_standard_envelope() -> None:
    with TestClient(app=app) as client:
        response = client.get("/api/does-not-exist", headers={"host": "localhost"})

    assert response.status_code == 404
    assert response.json() == {
        "status_code": 404,
        "error": "not_found",
        "detail": "Not Found",
        "request_id": response.headers["x-request-id"],
    }


def test_method_not_allowed_uses_a_client_error_category() -> None:
    with TestClient(app=app) as client:
        response = client.post("/api/health/live", headers={"host": "localhost"})

    assert response.status_code == 405
    assert response.json() == {
        "status_code": 405,
        "error": "method_not_allowed",
        "detail": "Method Not Allowed",
        "request_id": response.headers["x-request-id"],
    }
