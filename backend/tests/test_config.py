from app.config import Settings


def test_allowed_host_headers_preserve_wildcard() -> None:
    settings = Settings()
    settings.allowed_hosts = ("*",)

    assert settings.allowed_host_headers == ["*"]
