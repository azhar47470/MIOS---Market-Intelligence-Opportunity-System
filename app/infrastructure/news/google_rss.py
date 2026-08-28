"""Google News RSS connector — Tier 3 discovery layer."""

from __future__ import annotations

import logging
from xml.etree import ElementTree

from app.infrastructure.news.article import Article
from app.infrastructure.news.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)

QUERIES = [
    "gold price forecast",
    "federal reserve interest rates",
    "inflation CPI data",
    "geopolitical risk gold",
    "central bank gold purchases",
]


class GoogleRSSConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "google_rss"

    @property
    def tier(self) -> int:
        return 3

    @property
    def trust_score(self) -> float:
        return 7.0

    @property
    def rate_limit_per_minute(self) -> int:
        return 15

    def fetch(self) -> ConnectorResult:
        articles: list[Article] = []
        errors: list[str] = []
        for query in QUERIES:
            url = (
                "https://news.google.com/rss/search?q="
                f"{query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
            )
            try:
                articles.extend(self._parse_rss(self._get_text(url, timeout_seconds=10.0), query))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"query '{query}': {exc}")
        return ConnectorResult(self.name, articles, errors, len(articles))

    def _parse_rss(self, xml_text: str, query: str) -> list[Article]:
        articles: list[Article] = []
        try:
            root = ElementTree.fromstring(xml_text)
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                desc = (item.findtext("description") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                source_el = item.find("source")
                source_name = source_el.text if source_el is not None else "google_news"
                if not title:
                    continue
                articles.append(
                    Article(
                        title=title,
                        summary=desc[:500],
                        content=desc,
                        source=source_name or "google_news",
                        url=link,
                        published_at=self._parse_date(pub_date),
                        language="en",
                        categories=["discovery"],
                        metadata={"query": query},
                    )
                )
        except ElementTree.ParseError as exc:
            logger.error("Google RSS parse error: %s", exc)
        return articles