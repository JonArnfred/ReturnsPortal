from __future__ import annotations

import pytest
from pytest import MonkeyPatch

from app.config import settings
from app.services import secrets


def test_roundtrip_and_missing_key(monkeypatch: MonkeyPatch) -> None:
    secrets._fernet.cache_clear()
    monkeypatch.setattr(settings, "secrets_encryption_key", secrets.generate_key())
    token = secrets.encrypt("saxo-access-token")
    assert token != "saxo-access-token"
    assert secrets.decrypt(token) == "saxo-access-token"

    secrets._fernet.cache_clear()
    monkeypatch.setattr(settings, "secrets_encryption_key", secrets.generate_key())
    with pytest.raises(ValueError):
        secrets.decrypt(token)

    secrets._fernet.cache_clear()
    monkeypatch.setattr(settings, "secrets_encryption_key", None)
    with pytest.raises(secrets.SecretsNotConfiguredError):
        secrets.encrypt("x")
    secrets._fernet.cache_clear()
