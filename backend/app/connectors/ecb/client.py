"""ECB euro foreign exchange reference rates, published every TARGET working day around 16:00 CET.

Two feeds: the full history since 1999 (about 7 MB) and the last 90 days. Both are the same XML:
one ``Cube time`` per day with a ``Cube currency rate`` per currency, units of currency per euro.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

HISTORY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
RECENT_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"


@dataclass
class EcbFeed:
    url: str
    status_code: int
    text: str


class EcbClient:
    def __init__(self, http: httpx.Client | None = None) -> None:
        self._http = http or httpx.Client(timeout=60.0, follow_redirects=True)
        self._owned = http is None

    def fetch(self, full_history: bool) -> EcbFeed:
        url = HISTORY_URL if full_history else RECENT_URL
        response = self._http.get(url)
        return EcbFeed(url=url, status_code=response.status_code, text=response.text)

    def close(self) -> None:
        if self._owned:
            self._http.close()
