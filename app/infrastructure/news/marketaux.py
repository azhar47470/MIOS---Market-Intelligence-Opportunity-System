"""MarketAux connector — Tier 2 financial intelligence."""

from __future__ import annotations

import logging
import os

from app.infrastructure.news.article import Article
from app.infrastructure.news.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.marketaux.com/v1/news/all"

_QUERIES = ["gold", "federal reserve", "inflation", "central bank"]


class MarketAuxConnector(BaseConnector):
    def __init__(self, http_client):
        super().__init__(http_client)
        self.api_key = os.getenv("MARKETAUX_API_KEY", "")

    @property
    def name(self) -> str:
        return "marketaux"

    @property
    def tier(self) -> int:
        return 2

    @property
    def trust_score(self) -> float:
        return 9.0

    @property
    def rate_limit_per_minute(self) -> int:
        return 5

    def fetch(self) -> ConnectorResult:
        if not self.api_key:
            return ConnectorResult(self.name, [], ["No MARKETAUX_API_KEY"], 0)
        articles: list[Article] = []
        errors: list[str] = []
        for query in _QUERIES:
            try:
                data = self._get_json(
                    _BASE_URL,
                    params={
                        "api_token": self.api_key,
                        "search": query,
                        "language": "en",
                        "limit": "10",
                    },
                    timeout_seconds=15.0,
                )
                items = data.get("data", []) if isinstance(data, dict) else []
                logger.info("marketaux query '%s' returned %d raw items", query, len(items))
                for item in items:
                    try:
                        symbols: list[str] = []
                        entities = item.get("entities")
                        if isinstance(entities, dict):
                            for sym in entities.get("symbols") or []:
                                if isinstance(sym, dict):
                                    symbols.append(sym.get("symbol", ""))
                                elif isinstance(sym, str):
                                    symbols.append(sym)
                        articles.append(
                            Article(
                                title=item.get("title", ""),
                                summary=(item.get("description") or "")[:500],
                                content=item.get("snippet", "")
                                or item.get("description", "")
                                or "",
                                source="marketaux",
                                url=item.get("url", ""),
                                published_at=self._parse_date(item.get("published_at", "")),
                                language="en",
                                symbols=symbols,
                            )
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("marketaux item skipped: %s", exc)
                        continue
            except Exception as exc:  # noqa: BLE001
                errors.append(f"query {query}: {exc}")
        return ConnectorResult(self.name, articles, errors, len(articles))