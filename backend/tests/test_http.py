from __future__ import annotations

import pytest
from litestar.testing import TestClient

from app.api import app


@pytest.mark.parametrize(
    "headers",
    [
        {"sec-fetch-site": "cross-site"},
        {"sec-fetch-site": "same-site"},
        {"origin": "https://attacker.example"},
        {"origin": "https://attacker.example", "sec-fetch-site": "cross-site", "content-type": "text/plain"},
    ],
)
def test_cross_site_writes_are_rejected(headers: dict[str, str]) -> None:
    with TestClient(app=app, base_url="http://127.0.0.1") as client:
        response = client.post("/api/reports/rebuild", headers=headers, content=b"{}")
    assert response.status_code == 403 and response.json()["error"] == "forbidden"


def test_reads_are_not_checked() -> None:
    with TestClient(app=app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health/live", headers={"sec-fetch-site": "cross-site"}).status_code == 200
