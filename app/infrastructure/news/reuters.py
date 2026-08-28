"""Reuters connector — Tier 1 authoritative source (Google News site: proxy)."""

from __future__ import annotations

import logging
from xml.etree import ElementTree

from app.infrastructure.news.article import Article
from app.infrastructure.news.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)

REUTERS_FEEDS = [
    "https://news.google.com/rss/search?q=site:reuters.com+gold+OR+federal+reserve+OR+inflation&hl=en-US&gl=US&ceid=US:en",
]


class ReutersConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "reuters"

    @property
    def tier(self) -> int:
        return 1

    @property
    def trust_score(self) -> float:
        return 10.0

    @property
    def rate_limit_per_minute(self) -> int:
        return 10

    def fetch(self) -> ConnectorResult:
        articles: list[Article] = []
        errors: list[str] = []
        for feed_url in REUTERS_FEEDS:
            try:
                articles.extend(self._parse_rss(self._get_text(feed_url, timeout_seconds=15.0)))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{feed_url}: {exc}")
        return ConnectorResult(self.name, articles, errors, len(articles))

    def _parse_rss(self, xml_text: str) -> list[Article]:
        articles: list[Article] = []
        try:
            root = ElementTree.fromstring(xml_text)
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = (item.findtext("description") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                if not title:
                    continue
                articles.append(
                    Article(
                        title=title,
                        summary=desc[:500],
                        content=desc,
                        source="reuters",
                        url=link,
                        published_at=self._parse_date(pub_date),
                        language="en",
                        categories=["finance", "markets"],
                    )
                )
        except ElementTree.ParseError as exc:
            logger.error("Reuters RSS parse error: %s", exc)
        return articles