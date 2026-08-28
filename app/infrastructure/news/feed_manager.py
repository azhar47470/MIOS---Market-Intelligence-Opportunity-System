"""Feed Manager — orchestrates connector execution with rate limiting,
caching, and health monitoring (ported from the MIOS v2 news engine)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.infrastructure.news.article import Article
from app.infrastructure.news.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)


@dataclass
class SourceHealth:
    """Health tracking for a single source."""

    name: str
    total_fetches: int = 0
    total_errors: int = 0
    total_articles: int = 0
    last_success: float = 0.0
    last_error: str = ""
    consecutive_failures: int = 0

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_failures < 3

    @property
    def error_rate(self) -> float:
        if self.total_fetches == 0:
            return 0.0
        return self.total_errors / self.total_fetches


class FeedManager:
    """Manages all source connectors: health monitoring, caching, aggregation."""

    def __init__(self, connectors: list[BaseConnector] | None = None) -> None:
        self.connectors = connectors or []
        self.health: dict[str, SourceHealth] = {
            connector.name: SourceHealth(name=connector.name) for connector in self.connectors
        }
        self._cache: dict[str, list[Article]] = {}
        self._cache_ttl: float = 300.0
        self._cache_times: dict[str, float] = {}

    def fetch_all(self) -> list[Article]:
        """Fetch from all healthy connectors and return the unified article list."""
        all_articles: list[Article] = []

        for connector in self.connectors:
            health = self.health[connector.name]
            if not health.is_healthy:
                logger.warning(
                    "Skipping %s (unhealthy, %d consecutive failures)",
                    connector.name,
                    health.consecutive_failures,
                )
                all_articles.extend(self._get_cached(connector.name))
                continue

            result = connector.safe_fetch()
            health.total_fetches += 1
            health.total_articles += result.articles_fetched

            if result.errors:
                health.total_errors += len(result.errors)
                health.last_error = result.errors[-1]
                health.consecutive_failures += 1
            else:
                health.consecutive_failures = 0
                health.last_success = time.time()

            if result.articles:
                self._set_cache(connector.name, result.articles)
                all_articles.extend(result.articles)

        logger.info("FeedManager: %d articles from %d sources", len(all_articles), len(self.connectors))
        return all_articles

    def get_health_report(self) -> dict[str, dict]:
        """Get health status of all sources."""
        return {
            name: {
                "healthy": health.is_healthy,
                "total_fetches": health.total_fetches,
                "error_rate": round(health.error_rate, 3),
                "total_articles": health.total_articles,
                "consecutive_failures": health.consecutive_failures,
                "last_error": health.last_error,
            }
            for name, health in self.health.items()
        }

    def _get_cached(self, source: str) -> list[Article]:
        if source in self._cache:
            age = time.time() - self._cache_times.get(source, 0)
            if age < self._cache_ttl:
                return self._cache[source]
        return []

    def _set_cache(self, source: str, articles: list[Article]) -> None:
        self._cache[source] = articles
        self._cache_times[source] = time.time()