"""Encryption at rest for broker tokens, using Fernet with a key from the environment."""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretsNotConfiguredError(RuntimeError):
    pass


@lru_cache
def _fernet() -> Fernet:
    key = settings.secrets_encryption_key
    if not key:
        raise SecretsNotConfiguredError(
            "SECRETS_ENCRYPTION_KEY is not set; generate one with backend/scripts/generate_encryption_key.py"
        )
    return Fernet(key.encode("ascii"))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("stored secret cannot be decrypted with the configured SECRETS_ENCRYPTION_KEY") from exc


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")
