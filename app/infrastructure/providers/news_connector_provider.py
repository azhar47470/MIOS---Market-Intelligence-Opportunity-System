"""News connector provider — wraps the v2 connector layer + FeedManager.

Runs all 15 tiered connectors through the FeedManager (per-source health,
skip-unhealthy, 300s per-source cache) and normalizes results to the
platform's `NewsEventSnapshot` contract. Missing keys and dead feeds surface
as per-connector errors but never abort the shared fetch cycle.
"""

from __future__ import annotations

from app.application.http import HttpClient
from app.domain.common import (
    ContractMetadata,
    ContractStatus,
    DataQuality,
    ProviderResult,
)
from app.domain.provider_snapshots import NewsEventSnapshot
from app.infrastructure.news import build_all_connectors
from app.infrastructure.news.feed_manager import FeedManager
from app.infrastructure.news.relevance import RELEVANCE_THRESHOLD, GoldRelevanceEngine
from app.infrastructure.news.topics import TopicClassifier
from app.infrastructure.providers.base import parse_datetime


class NewsConnectorProvider:
    """Fetch news through the 15-connector v2 layer with per-source health."""

    def __init__(
        self,
        http_client: HttpClient,
        feed_manager: FeedManager | None = None,
    ) -> None:
        self._feed_manager = feed_manager or FeedManager(build_all_connectors(http_client))
        self._topic_classifier = TopicClassifier()
        self._relevance_engine = GoldRelevanceEngine()

    @property
    def feed_manager(self) -> FeedManager:
        return self._feed_manager

    async def fetch_all(self) -> ProviderResult[tuple[NewsEventSnapshot, ...]]:
        """Fetch from all healthy connectors, run v2 pipeline stages (topics,
        gold-relevance filter), and return normalized snapshots."""
        events: list[NewsEventSnapshot] = []
        for article in self._feed_manager.fetch_all():
            if not article.title or not article.url:
                continue
            if self._relevance_engine.score(article) < RELEVANCE_THRESHOLD:
                continue
            article.metadata["topics"] = list(self._topic_classifier.classify(article))
            events.append(
                NewsEventSnapshot(
                    headline=article.title[:500],
                    url=article.url,
                    tone=None,
                    date=parse_datetime(article.published_at),
                    source=article.source[:120],
                )
            )
        errors = self._collect_errors()
        if events:
            return self._result(
                ContractStatus.SUCCESS,
                tuple(events),
                error="; ".join(errors)[:1000] if errors else None,
            )
        if errors:
            return self._result(
                ContractStatus.FAILED,
                None,
                error="; ".join(errors)[:1000],
            )
        return self._result(
            ContractStatus.SUCCESS,
            (),
            error=None,
        )

    def get_health_report(self) -> dict[str, dict]:
        return self._feed_manager.get_health_report()

    def _collect_errors(self) -> list[str]:
        seen: list[str] = []
        for health in self._feed_manager.health.values():
            if health.last_error and health.last_error not in seen:
                seen.append(health.last_error)
        return seen

    def _result(
        self,
        status: ContractStatus,
        data: tuple[NewsEventSnapshot, ...] | None,
        error: str | None = None,
    ) -> ProviderResult[tuple[NewsEventSnapshot, ...]]:
        return ProviderResult(
            status=status,
            provider="news_connectors",
            metadata=ContractMetadata(),
            data=data,
            quality=DataQuality.FRESH if status == ContractStatus.SUCCESS else DataQuality.UNKNOWN,
            error=error,
        )