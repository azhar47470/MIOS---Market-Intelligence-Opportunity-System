"""Base connector for the v2 news-engine port.

Handles rate limiting, error capture, date parsing, and HTTP access through the
platform's existing `HttpClient` protocol so the connector layer stays within the
stdlib-only `UrlLibHttpClient` stack (no new HTTP dependency).
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from app.application.http import HttpClient, HttpResponse
from app.infrastructure.news.article import Article

logger = logging.getLogger(__name__)


@dataclass
class ConnectorResult:
    """Result from a single connector fetch cycle."""

    connector_name: str
    articles: list[Article] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    articles_fetched: int = 0
    elapsed_ms: float = 0.0


class BaseConnector(ABC):
    """Abstract base for all source connectors."""

    def __init__(self, http_client: HttpClient) -> None:
        self._http = http_client
        self._last_fetch: float = 0.0
        self._min_interval: float = 60.0 / max(self.rate_limit_per_minute, 1)

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique connector identifier."""

    @property
    @abstractmethod
    def tier(self) -> int:
        """Source tier (1=authoritative, 5=emergency)."""

    @property
    @abstractmethod
    def trust_score(self) -> float:
        """Base trust score (0-10)."""

    @property
    @abstractmethod
    def rate_limit_per_minute(self) -> int:
        """Max requests per minute for this source."""

    @abstractmethod
    def fetch(self) -> ConnectorResult:
        """Fetch articles from the source. Must be implemented by subclass."""

    def safe_fetch(self) -> ConnectorResult:
        """Fetch with rate limiting and error handling."""
        now = time.time()
        elapsed = now - self._last_fetch
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.debug("%s: rate limiting, waiting %.1fs", self.name, wait)
            time.sleep(wait)

        start = time.time()
        try:
            result = self.fetch()
            result.elapsed_ms = (time.time() - start) * 1000
            self._last_fetch = time.time()
            logger.info(
                "%s: fetched %d articles in %.0fms",
                self.name,
                result.articles_fetched,
                result.elapsed_ms,
            )
            return result
        except Exception as exc:  # noqa: BLE001 - connectors must never crash the fetch cycle
            logger.error("%s: fetch failed — %s", self.name, exc)
            return ConnectorResult(connector_name=self.name, errors=[str(exc)])

    def _get_text(
        self,
        url: str,
        params: dict[str, str] | None = None,
        timeout_seconds: float = 15.0,
    ) -> str:
        response = self._request(url, params, timeout_seconds)
        return response.body

    def _get_json(
        self,
        url: str,
        params: dict[str, str] | None = None,
        timeout_seconds: float = 15.0,
    ) -> dict | list:
        response = self._request(url, params, timeout_seconds)
        return json.loads(response.body)

    def _request(
        self,
        url: str,
        params: dict[str, str] | None,
        timeout_seconds: float,
    ) -> HttpResponse:
        response = self._http.get(url, params=params, timeout_seconds=timeout_seconds)
        if response.status_code != 200:
            raise RuntimeError(f"HTTP {response.status_code}: {response.body[:200]}")
        return response

    def _parse_date(self, date_str: str) -> str:
        """Parse various date formats into ISO 8601 (naive ok; normalized later)."""
        if not date_str:
            return datetime.now(UTC).isoformat()

        try:
            dt = parsedate_to_datetime(date_str)
            return dt.isoformat()
        except (ValueError, TypeError):
            pass

        # datetime.fromisoformat handles RFC3339 and fractional seconds ("Z" is not
        # accepted until 3.11+, so normalize it to an explicit offset first).
        try:
            return datetime.fromisoformat(date_str.strip().replace("Z", "+00:00")).isoformat()
        except (ValueError, TypeError):
            pass

        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.isoformat()
            except ValueError:
                continue

        return datetime.now(UTC).isoformat()