"""Tier-1 official sources: RSS + Atom support, Google News proxies for dead feeds."""

from __future__ import annotations

import logging
from typing import Any
from xml.etree import ElementTree

from app.infrastructure.news.article import Article
from app.infrastructure.news.base import BaseConnector, ConnectorResult

logger = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"
GOOGLE = "https://news.google.com/rss/search?q=site:%s&hl=en-US&gl=US&ceid=US:en"


def _parse(xml_text: str, source: str, parse_date_fn) -> list[Article]:
    articles: list[Article] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        logger.error("%s xml parse error: %s", source, exc)
        return articles
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if title:
            articles.append(
                Article(
                    title=title,
                    summary=desc[:500],
                    content=desc,
                    source=source,
                    url=link,
                    published_at=parse_date_fn(pub),
                    language="en",
                )
            )
    if articles:
        return articles
    for entry in root.iter(ATOM + "entry"):
        title = (entry.findtext(ATOM + "title") or "").strip()
        link_el = entry.find(ATOM + "link")
        link = link_el.get("href", "") if link_el is not None else ""
        desc = (
            entry.findtext(ATOM + "summary")
            or entry.findtext(ATOM + "content")
            or ""
        ).strip()
        pub = (
            entry.findtext(ATOM + "published")
            or entry.findtext(ATOM + "updated")
            or ""
        ).strip()
        if title:
            articles.append(
                Article(
                    title=title,
                    summary=desc[:500],
                    content=desc,
                    source=source,
                    url=link,
                    published_at=parse_date_fn(pub),
                    language="en",
                )
            )
    return articles


class _OfficialBase(BaseConnector):
    feeds: list[tuple[str, str]] = []
    src = ""

    @property
    def name(self) -> str:
        return self.src

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
        for url, label in self.feeds:
            try:
                articles.extend(_parse(self._get_text(url, timeout_seconds=15.0), label, self._parse_date))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{url}: {exc}")
        return ConnectorResult(self.src, articles, errors, len(articles))


class IMFConnector(_OfficialBase):
    src = "imf"
    trust_score = 10.0
    feeds = [(GOOGLE % "imf.org", "imf")]


class BISConnector(_OfficialBase):
    src = "bis"
    trust_score = 10.0
    rate_limit_per_minute = 3
    feeds = [("https://www.bis.org/doclist/all_pressrels.rss", "bis")]


class TreasuryConnector(_OfficialBase):
    src = "treasury"
    trust_score = 10.0
    feeds = [
        ("https://home.treasury.gov/news/press-releases/rss.xml", "treasury"),
        (GOOGLE % "home.treasury.gov", "treasury"),
    ]


class WGCConnector(_OfficialBase):
    src = "wgc"
    trust_score = 9.5
    feeds = [(GOOGLE % "gold.org", "wgc")]


class CFTCConnector(_OfficialBase):
    src = "cftc"
    trust_score = 10.0
    feeds = [(GOOGLE % "cftc.gov", "cftc")]


class LBMAConnector(_OfficialBase):
    src = "lbma"
    trust_score = 9.5
    feeds = [(GOOGLE % "lbma.org.uk", "lbma")]