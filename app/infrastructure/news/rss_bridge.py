"""RSS Bridge — Tier 5 emergency fallback (Kitco, Bloomberg)."""

from __future__ import annotations

import logging
from xml.etree import ElementTree

from app.infrastructure.news.article import Article
from app.infrastructure.news.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)

FALLBACK_FEEDS = [
    ("https://www.kitco.com/rss/news.xml", "kitco"),
    ("https://feeds.bloomberg.com/markets/news.rss", "bloomberg"),
]


class RSSBridgeConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "rss_bridge"

    @property
    def tier(self) -> int:
        return 5

    @property
    def trust_score(self) -> float:
        return 5.0

    @property
    def rate_limit_per_minute(self) -> int:
        return 10

    def fetch(self) -> ConnectorResult:
        articles: list[Article] = []
        errors: list[str] = []
        for feed_url, source_name in FALLBACK_FEEDS:
            try:
                articles.extend(
                    self._parse_rss(self._get_text(feed_url, timeout_seconds=10.0), source_name)
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{source_name}: {exc}")
        return ConnectorResult(self.name, articles, errors, len(articles))

    def _parse_rss(self, xml_text: str, source: str) -> list[Article]:
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
                        source=source,
                        url=link,
                        published_at=self._parse_date(pub_date),
                        language="en",
                    )
                )
        except ElementTree.ParseError as exc:
            logger.error("%s parse error: %s", source, exc)
        return articles