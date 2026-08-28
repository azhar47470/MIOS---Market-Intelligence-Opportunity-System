"""Finnhub connector — Tier 2 financial intelligence (news only, not calendar)."""

from __future__ import annotations

import logging
import os

from app.infrastructure.news.article import Article
from app.infrastructure.news.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://finnhub.io/api/v1/news"

_CATEGORIES = ["general", "forex"]


class FinnhubConnector(BaseConnector):
    def __init__(self, http_client):
        super().__init__(http_client)
        self.api_key = os.getenv("FINNHUB_API_KEY", "")

    @property
    def name(self) -> str:
        return "finnhub"

    @property
    def tier(self) -> int:
        return 2

    @property
    def trust_score(self) -> float:
        return 8.5

    @property
    def rate_limit_per_minute(self) -> int:
        return 10

    def fetch(self) -> ConnectorResult:
        if not self.api_key:
            return ConnectorResult(self.name, [], ["No FINNHUB_API_KEY"], 0)
        articles: list[Article] = []
        errors: list[str] = []
        for category in _CATEGORIES:
            try:
                data = self._get_json(
                    _BASE_URL,
                    params={"token": self.api_key, "category": category},
                    timeout_seconds=15.0,
                )
                if isinstance(data, list):
                    for item in data[:20]:
                        articles.append(
                            Article(
                                title=item.get("headline", ""),
                                summary=item.get("summary", "")[:500],
                                content=item.get("content", ""),
                                source="finnhub",
                                url=item.get("url", ""),
                                published_at=self._parse_date(str(item.get("datetime", ""))),
                                language="en",
                            )
                        )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"category '{category}': {exc}")
        return ConnectorResult(self.name, articles, errors, len(articles))