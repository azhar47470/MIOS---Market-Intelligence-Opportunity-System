"""Tier 4 discovery APIs: TheNewsAPI, WorldNewsAPI."""

from __future__ import annotations

import logging
import os

from app.infrastructure.news.article import Article
from app.infrastructure.news.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)


class TheNewsAPIConnector(BaseConnector):
    BASE_URL = "https://api.thenewsapi.com/v1/news/all"

    def __init__(self, http_client):
        super().__init__(http_client)
        self.api_key = os.getenv("THENEWSAPI_KEY", "")

    @property
    def name(self) -> str:
        return "thenewsapi"

    @property
    def tier(self) -> int:
        return 4

    @property
    def trust_score(self) -> float:
        return 6.0

    @property
    def rate_limit_per_minute(self) -> int:
        return 3

    def fetch(self) -> ConnectorResult:
        if not self.api_key:
            return ConnectorResult(self.name, [], ["No THENEWSAPI_KEY"], 0)
        articles: list[Article] = []
        errors: list[str] = []
        for query in ["gold price", "federal reserve", "inflation"]:
            try:
                data = self._get_json(
                    self.BASE_URL,
                    params={
                        "api_token": self.api_key,
                        "search": query,
                        "language": "en",
                        "limit": "10",
                    },
                    timeout_seconds=15.0,
                )
                for item in data.get("data", []):
                    articles.append(
                        Article(
                            title=item.get("title", ""),
                            summary=item.get("description", "")[:500],
                            content=item.get("snippet", ""),
                            source=item.get("source", "thenewsapi"),
                            url=item.get("url", ""),
                            published_at=self._parse_date(item.get("published_at", "")),
                            language="en",
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        return ConnectorResult(self.name, articles, errors, len(articles))


class WorldNewsAPIConnector(BaseConnector):
    BASE_URL = "https://api.worldnewsapi.com/search-news"

    def __init__(self, http_client):
        super().__init__(http_client)
        self.api_key = os.getenv("WORLDNEWSAPI_KEY", "")

    @property
    def name(self) -> str:
        return "worldnewsapi"

    @property
    def tier(self) -> int:
        return 4

    @property
    def trust_score(self) -> float:
        return 6.0

    @property
    def rate_limit_per_minute(self) -> int:
        return 3

    def fetch(self) -> ConnectorResult:
        if not self.api_key:
            return ConnectorResult(self.name, [], ["No WORLDNEWSAPI_KEY"], 0)
        articles: list[Article] = []
        errors: list[str] = []
        for query in ["gold", "central bank", "inflation"]:
            try:
                data = self._get_json(
                    self.BASE_URL,
                    params={
                        "api-key": self.api_key,
                        "text": query,
                        "language": "en",
                        "number": "10",
                    },
                    timeout_seconds=15.0,
                )
                for item in data.get("news", []):
                    articles.append(
                        Article(
                            title=item.get("title", ""),
                            summary=item.get("summary", "")[:500],
                            content=item.get("text", "")[:2000],
                            source=item.get("source_name", "worldnewsapi"),
                            url=item.get("url", ""),
                            published_at=self._parse_date(item.get("publish_date", "")),
                            language="en",
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        return ConnectorResult(self.name, articles, errors, len(articles))