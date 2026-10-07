"""Minimal HTTP client for the Saxo OpenAPI: bearer auth, paging, and rate-limit retries."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("returns-portal.saxo")

MAX_PAGES = 200
MAX_RETRIES = 5


@dataclass(frozen=True)
class FetchResult:
    """One HTTP response, kept whether or not it succeeded."""

    endpoint: str
    params: dict[str, Any]
    status_code: int
    payload: Any
    url: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def data(self) -> list[Any]:
        """The ``Data`` array of a Saxo list response, or an empty list."""
        if isinstance(self.payload, dict) and isinstance(self.payload.get("Data"), list):
            return list(self.payload["Data"])
        return []


@dataclass
class SaxoClient:
    access_token: str
    api_base: str
    http: httpx.Client | None = None
    sleep: Any = field(default=time.sleep)
    # Called once on a 401 for a current token: a long sync can outlive the access token it started with.
    token_provider: Callable[[], str] | None = None

    def __post_init__(self) -> None:
        self._owned = self.http is None
        self.http = self.http or httpx.Client(timeout=60)

    def close(self) -> None:
        if self._owned and self.http is not None:
            self.http.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}

    def _get(self, url: str, params: dict[str, Any] | None) -> httpx.Response:
        assert self.http is not None
        renewed = False
        for attempt in range(MAX_RETRIES):
            response = self.http.get(url, params=params, headers=self._headers())
            if response.status_code == 401 and self.token_provider is not None and not renewed:
                renewed = True
                token = self.token_provider()
                if token != self.access_token:
                    logger.info("Saxo access token renewed during a request run")
                    self.access_token = token
                    continue
            if response.status_code != 429:
                return response
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0 * (attempt + 1)
            logger.warning("Saxo rate limit hit on %s; sleeping %.1fs", url, delay)
            self.sleep(delay)
        return response

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return {"_raw_text": response.text[:10_000]}

    def _same_api(self, url: str) -> bool:
        """Whether an absolute URL points into this client's API, so the bearer token may go there."""
        return url == self.api_base or url.startswith(f"{self.api_base.rstrip('/')}/")

    def fetch(self, endpoint: str, params: dict[str, Any] | None = None) -> FetchResult:
        if endpoint.startswith("http") and not self._same_api(endpoint):
            raise ValueError("Refusing to send the Saxo token outside the API base URL")
        url = endpoint if endpoint.startswith("http") else f"{self.api_base}/{endpoint.lstrip('/')}"
        response = self._get(url, params)
        return FetchResult(
            endpoint, dict(params or {}), response.status_code, self._decode(response), str(response.url)
        )

    def fetch_pages(self, endpoint: str, params: dict[str, Any] | None = None) -> list[FetchResult]:
        """Follow Saxo's ``__next`` links. Every page is returned, including a failed first page."""
        pages: list[FetchResult] = []
        result = self.fetch(endpoint, params)
        pages.append(result)
        while result.ok and isinstance(result.payload, dict) and result.payload.get("__next"):
            if len(pages) >= MAX_PAGES:
                logger.warning("Saxo paging stopped at %d pages for %s", MAX_PAGES, endpoint)
                break
            next_url = str(result.payload["__next"])
            if not self._same_api(next_url):
                logger.warning("Saxo paging stopped: the next link for %s leaves the API base URL", endpoint)
                break
            response = self._get(next_url, None)
            result = FetchResult(endpoint, {"__next": next_url}, response.status_code, self._decode(response), next_url)
            pages.append(result)
        return pages
