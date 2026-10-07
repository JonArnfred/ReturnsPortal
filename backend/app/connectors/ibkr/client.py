"""Flex Web Service client: ask for a statement, poll until it is generated, return the XML.

Two GET requests: ``SendRequest`` answers with a reference code, ``GetStatement`` with the report
once IBKR has built it (error 1019 while it is still generating). The token travels as a query
parameter, so the ``httpx`` request log line is silenced and HTTP failures are re-raised as
``FlexHttpError``, whose message has no URL (httpx puts the full URL, token included, in its own).
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger("returns-portal.ibkr")
logging.getLogger("httpx").setLevel(max(logging.getLogger("httpx").level, logging.WARNING))

SEND_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
GET_URL = "https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
USER_AGENT = "returns-portal/1.0"
VERSION = "3"

# Statement not ready yet: keep polling. 1019 is "generation in progress"; the others are
# "<x> data is not ready at this time, try again shortly".
RETRY_CODES = frozenset({"1001", "1004", "1005", "1006", "1007", "1008", "1009", "1019"})
THROTTLE_CODE = "1018"
# The token itself is the problem: expired, invalid, or used from a different IP than it allows.
CREDENTIAL_CODES = frozenset({"1011", "1012", "1013", "1015"})
POLL_SECONDS = 5.0
THROTTLE_SECONDS = 15.0
SEND_THROTTLE_SECONDS = 60.0
SEND_THROTTLE_RETRIES = 3
MAX_POLLS = 40
TIMEOUT_CODE = "timeout"


class FlexHttpError(RuntimeError):
    """A failed request to the Flex Web Service; the message never contains the token."""


@dataclass(frozen=True)
class FlexResult:
    """One statement request. ``params`` never contains the token."""

    params: dict[str, str]
    reference_code: str | None
    text: str
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None

    @property
    def credential_problem(self) -> bool:
        return self.error_code in CREDENTIAL_CODES


def _status_fields(text: str) -> dict[str, str]:
    """Fields of a ``FlexStatementResponse`` (Status, ReferenceCode, ErrorCode, ErrorMessage)."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {"Status": "Fail", "ErrorCode": "unparseable", "ErrorMessage": text[:200]}
    return {child.tag: (child.text or "").strip() for child in root}


def is_statement(text: str) -> bool:
    return "<FlexQueryResponse" in text[:2000]


def window_params(
    query_id: str, *, period_days: int | None = None, from_date: date | None = None, to_date: date | None = None
) -> dict[str, str]:
    """Query parameters for one pull: either ``p`` (last N calendar days) or ``fd``/``td``."""
    params = {"q": query_id, "v": VERSION}
    if period_days is not None:
        params["p"] = str(period_days)
    elif from_date is not None and to_date is not None:
        params["fd"] = from_date.strftime("%Y%m%d")
        params["td"] = to_date.strftime("%Y%m%d")
    return params


@dataclass
class FlexClient:
    token: str
    http: httpx.Client | None = None
    sleep: Any = field(default=time.sleep)
    poll_seconds: float = POLL_SECONDS

    def __post_init__(self) -> None:
        self._owned = self.http is None
        self.http = self.http or httpx.Client(timeout=120, headers={"User-Agent": USER_AGENT})

    def close(self) -> None:
        if self._owned and self.http is not None:
            self.http.close()

    def _get(self, url: str, params: dict[str, str]) -> str:
        assert self.http is not None
        endpoint = url.rsplit("/", 1)[-1]
        try:
            response = self.http.get(url, params={**params, "t": self.token}, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # ``from None``: a chained httpx error would bring the URL back into tracebacks.
            raise FlexHttpError(f"Flex {endpoint} answered HTTP {exc.response.status_code}") from None
        except httpx.HTTPError as exc:
            raise FlexHttpError(f"Flex {endpoint} request failed: {type(exc).__name__}") from None
        return response.text

    def fetch_statement(self, params: dict[str, str]) -> FlexResult:
        """Run the query described by ``params`` (see ``window_params``) and wait for the statement."""
        text = self._get(SEND_URL, params)
        fields = _status_fields(text)
        for _ in range(SEND_THROTTLE_RETRIES):
            if fields.get("ErrorCode") != THROTTLE_CODE:
                break
            # The limit is per token over about two minutes, so wait out a good part of that window.
            logger.warning("Flex Web Service throttled the request; waiting %.0fs", SEND_THROTTLE_SECONDS)
            self.sleep(SEND_THROTTLE_SECONDS)
            text = self._get(SEND_URL, params)
            fields = _status_fields(text)
        if fields.get("Status") != "Success" or not fields.get("ReferenceCode"):
            return FlexResult(params, None, text, fields.get("ErrorCode") or "unknown", fields.get("ErrorMessage"))
        reference = fields["ReferenceCode"]
        for _ in range(MAX_POLLS):
            text = self._get(GET_URL, {"q": reference, "v": VERSION})
            if is_statement(text):
                return FlexResult(params, reference, text)
            fields = _status_fields(text)
            code = fields.get("ErrorCode") or "unknown"
            if code == THROTTLE_CODE:
                logger.warning("Flex Web Service throttled the token; waiting %.0fs", THROTTLE_SECONDS)
                self.sleep(THROTTLE_SECONDS)
            elif code in RETRY_CODES:
                self.sleep(self.poll_seconds)
            else:
                return FlexResult(params, reference, text, code, fields.get("ErrorMessage"))
        return FlexResult(params, reference, "", TIMEOUT_CODE, f"statement not generated after {MAX_POLLS} polls")
