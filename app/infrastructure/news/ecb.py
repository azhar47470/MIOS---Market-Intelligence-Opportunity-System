"""ECB connector — Tier 1 authoritative source (official RSS)."""

from __future__ import annotations

import logging
from xml.etree import ElementTree

from app.infrastructure.news.article import Article
from app.infrastructure.news.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)

ECB_FEEDS = [
    "https://www.ecb.europa.eu/rss/press.html",
]


class ECBConnector(BaseConnector):
    @property
    def name(self) -> str:
        return "ecb"

    @property
    def tier(self) -> int:
        return 1

    @property
    def trust_score(self) -> float:
        return 10.0

    @property
    def rate_limit_per_minute(self) -> int:
        return 5

    def fetch(self) -> ConnectorResult:
        articles: list[Article] = []
        errors: list[str] = []
        for feed_url in ECB_FEEDS:
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
                        source="ecb",
                        url=link,
                        published_at=self._parse_date(pub_date),
                        language="en",
                        categories=["central_bank", "monetary_policy"],
                        region="europe",
                    )
                )
        except ElementTree.ParseError as exc:
            logger.error("ECB feed parse error: %s", exc)
        return articles