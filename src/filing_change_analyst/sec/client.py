"""SEC EDGAR HTTP client: identified, rate-limited, cached, bounded retries."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from ..config import SEC_MIN_REQUEST_INTERVAL_S, get_settings
from ..services.cache import DiskCache

log = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

# Cache lifetimes. Filing archives are immutable once published; the submissions
# and ticker indexes change, so they get a shorter TTL.
TTL_IMMUTABLE = None  # never expires
TTL_INDEX = 60 * 60 * 12  # 12 hours


class SecError(RuntimeError):
    """Raised when SEC data cannot be obtained. Always carries a user-safe message."""


class OfflineError(SecError):
    """Raised when a resource is not cached and the app is in offline mode."""


class SecClient:
    """Minimal EDGAR client.

    Deliberately hand-rolled rather than pulling in EdgarTools: we need exact
    control over caching, the ``accn`` field on every XBRL fact (which is what
    makes provenance auditable) and offline behaviour for tests.
    """

    _rate_lock = threading.Lock()
    _last_request_at = 0.0

    def __init__(self, cache: DiskCache | None = None, client: httpx.Client | None = None) -> None:
        self.settings = get_settings()
        self.cache = cache or DiskCache()
        self._client = client
        self._owns_client = client is None

    # -- plumbing ---------------------------------------------------------- #

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.settings.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        }

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self.settings.http_timeout),
                follow_redirects=True,
                headers=self.headers,
            )
        return self._client

    @classmethod
    def _throttle(cls) -> None:
        with cls._rate_lock:
            delta = time.monotonic() - cls._last_request_at
            if delta < SEC_MIN_REQUEST_INTERVAL_S:
                time.sleep(SEC_MIN_REQUEST_INTERVAL_S - delta)
            cls._last_request_at = time.monotonic()

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self) -> SecClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- fetching ---------------------------------------------------------- #

    def fetch(self, url: str, *, ttl: float | None = TTL_IMMUTABLE, refresh: bool = False) -> bytes:
        """Fetch ``url`` through the cache with bounded retries."""
        if not refresh:
            cached = self.cache.get(url, max_age_s=ttl)
            if cached is not None:
                log.debug("cache hit %s", url)
                return cached

        if self.settings.offline:
            raise OfflineError(
                f"Offline mode is on and {url} is not cached. "
                "Unset FCA_OFFLINE=1 to allow network access."
            )

        last_error: Exception | None = None
        for attempt in range(1, max(1, self.settings.http_max_retries) + 1):
            self._throttle()
            try:
                resp = self._http().get(url, headers=self.headers)
            except httpx.HTTPError as exc:  # timeout, DNS, connection reset
                last_error = exc
                log.warning("SEC request failed (%s/%s): %s", attempt, self.settings.http_max_retries, exc)
            else:
                if resp.status_code == 200:
                    payload = resp.content
                    self.cache.put(url, payload)
                    return payload
                if resp.status_code in (403, 429) or resp.status_code >= 500:
                    last_error = SecError(f"SEC returned HTTP {resp.status_code} for {url}")
                    log.warning(
                        "SEC returned %s (%s/%s) for %s",
                        resp.status_code,
                        attempt,
                        self.settings.http_max_retries,
                        url,
                    )
                else:
                    raise SecError(f"SEC returned HTTP {resp.status_code} for {url}")
            if attempt < max(1, self.settings.http_max_retries):
                # Back off between attempts only. Sleeping after the final one
                # just delays the stale-cache fallback by up to 8 seconds.
                time.sleep(min(2.0**attempt * 0.5, 8.0))

        # Fall back to a stale cache entry rather than failing the whole demo.
        stale = self.cache.get(url, max_age_s=None)
        if stale is not None:
            log.warning("Using stale cached copy of %s after fetch failures", url)
            return stale

        hint = ""
        if not self.settings.sec_identity_configured():
            hint = (
                " SEC_USER_AGENT is not configured with a real 'Name email' value; "
                "SEC blocks unidentified clients."
            )
        raise SecError(f"Could not fetch {url}: {last_error}.{hint}")

    def fetch_json(self, url: str, *, ttl: float | None = TTL_IMMUTABLE, refresh: bool = False) -> Any:
        import json

        raw = self.fetch(url, ttl=ttl, refresh=refresh)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            self.cache.invalidate(url)
            raise SecError(f"SEC returned malformed JSON for {url}") from exc

    # -- typed endpoints --------------------------------------------------- #

    @staticmethod
    def cik10(cik: str | int) -> str:
        return str(int(cik)).zfill(10)

    def ticker_map(self, refresh: bool = False) -> dict[str, dict[str, str]]:
        """`{TICKER: {"cik": "0000789019", "title": "MICROSOFT CORP"}}`."""
        data = self.fetch_json(COMPANY_TICKERS_URL, ttl=TTL_INDEX, refresh=refresh)
        out: dict[str, dict[str, str]] = {}
        rows = data.values() if isinstance(data, dict) else data
        for row in rows:
            try:
                out[str(row["ticker"]).upper()] = {
                    "cik": self.cik10(row["cik_str"]),
                    "title": str(row["title"]),
                }
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def resolve_ticker(self, ticker: str) -> tuple[str, str]:
        """Return ``(cik10, company_name)``; raises :class:`SecError` if unknown."""
        t = ticker.strip().upper()
        if not t or not t.replace("-", "").replace(".", "").isalnum():
            raise SecError(f"'{ticker}' is not a valid ticker symbol.")
        mapping = self.ticker_map()
        if t not in mapping:
            raise SecError(f"Ticker '{t}' was not found in the SEC company index.")
        return mapping[t]["cik"], mapping[t]["title"]

    def submissions(self, cik: str, refresh: bool = False) -> dict[str, Any]:
        return self.fetch_json(
            SUBMISSIONS_URL.format(cik10=self.cik10(cik)), ttl=TTL_INDEX, refresh=refresh
        )

    def company_facts(self, cik: str, refresh: bool = False) -> dict[str, Any]:
        return self.fetch_json(
            COMPANY_FACTS_URL.format(cik10=self.cik10(cik)), ttl=TTL_INDEX, refresh=refresh
        )

    def filing_document(self, cik: str, accession: str, document: str, refresh: bool = False) -> bytes:
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{document}"
        )
        return self.fetch(url, ttl=TTL_IMMUTABLE, refresh=refresh)
