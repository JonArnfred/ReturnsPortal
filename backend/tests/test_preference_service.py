from __future__ import annotations

from app.services import preference_service


def test_preference_keys_are_kind_colon_name() -> None:
    assert preference_service.valid_key("filters:orders")
    assert preference_service.valid_key("filters:pnl-report")
    assert not preference_service.valid_key("orders")
    assert not preference_service.valid_key("Filters:Orders")
    assert not preference_service.valid_key("filters:orders/../x")
