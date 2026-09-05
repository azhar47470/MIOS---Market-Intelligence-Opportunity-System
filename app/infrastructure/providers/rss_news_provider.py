"""RSS news provider — keyless news ingestion ported from the v2 connector layer.

Fetches gold-relevant headlines via Google News RSS feeds (no API key needed),
applies v2's deduplication and gold-relevance filtering, and emits the same
NewsEventSnapshot contract as GDELT/NewsAPI so it can slot into the existing
news repository chain.
"""

import hashlib
import logging
import os
import re
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

from app.domain.common import ContractStatus, ProviderResult
from app.domain.provider_snapshots import NewsEventSnapshot
from app.infrastructure.providers.base import ProviderBase, parse_datetime

logger = logging.getLogger(__name__)

_DIRECT_SIGNALS = (
    "gold", "bullion", "xau", "precious metal", "gold price", "gold etf",
    "spdr gold", "gold mining",
)
_MACRO_SIGNALS = (
    "federal reserve", "fed", "interest rate", "inflation", "cpi", "dollar",
    "dxy", "treasury", "real yield", "monetary policy", "rate cut", "rate hike",
)
_GEO_SIGNALS = (
    "war", "sanctions", "geopolitical", "crisis", "conflict", "iran", "israel",
    "russia", "ukraine", "middle east", "red sea",
)
_SAFE_HAVEN_SIGNALS = (
    "safe haven", "uncertainty", "risk off", "flight to safety", "market crash",
    "recession fear",
)

_RELEVANCE_THRESHOLD = 0.10


class RSSNewsProvider(ProviderBase):
    """Ported v2 connectors: Reuters site-search plus Google News discovery feeds.

    Each feed is fetched through the configured ``google_news`` endpoint; the
    source outlet is preserved from each RSS item's ``<source>`` element so the
    cross-source verifier can still resolve authoritative tiers downstream.
    """

    _FEED_QUERIES: tuple[tuple[str, str], ...] = (
        ("reuters_gold", 'site:reuters.com gold OR "federal reserve" OR inflation'),
        ("gold_forecast", "gold price forecast"),
        ("fed_rates", "federal reserve interest rates"),
        ("inflation_cpi", "inflation CPI data"),
        ("geopolitical_gold", "geopolitical risk gold"),
        ("central_bank_gold", "central bank gold purchases"),
    )

    _KEYED_APIS: tuple[dict[str, Any], ...] = (
        {
            "name": "marketaux",
            "env_var": "MARKETAUX_API_KEY",
            "api_key_param": "api_token",
            "endpoint": "marketaux_all",
            "queries": ("gold", "federal reserve", "inflation", "central bank"),
            "items_path": ("data",),
            "field_map": {
                "title": "title",
                "description": "description",
                "url": "url",
                "date": "published_at",
                "source": "source",
            },
        },
        {
            "name": "thenewsapi",
            "env_var": "THENEWSAPI_KEY",
            "api_key_param": "api_token",
            "endpoint": "thenewsapi_all",
            "queries": ("gold price", "federal reserve", "inflation"),
            "items_path": ("data",),
            "field_map": {
                "title": "title",
                "description": "description",
                "url": "url",
                "date": "published_at",
                "source": "source",
            },
        },
        {
            "name": "worldnewsapi",
            "env_var": "WORLDNEWSAPI_KEY",
            "api_key_param": "api-key",
            "endpoint": "worldnewsapi_search",
            "queries": ("gold", "central bank", "inflation"),
            "items_path": ("news",),
            "field_map": {
                "title": "title",
                "description": "summary",
                "url": "url",
                "date": "publish_date",
                "source": "source_name",
            },
        },
    )

    async def news_events(self, query: str) -> ProviderResult[tuple[NewsEventSnapshot, ...]]:
        raw_articles: list[dict[str, Any]] = []
        errors: list[str] = []
        for feed_name, feed_query in self._FEED_QUERIES:
            status, text, error = self._get_text("google_news", {"q": feed_query})
            if status != ContractStatus.SUCCESS:
                errors.append(f"{feed_name}: {error}")
                continue
            try:
                raw_articles.extend(self._parse_rss(text or ""))
            except ElementTree.ParseError as exc:
                errors.append(f"{feed_name}: RSS parse error: {exc}")
        api_articles, api_errors = self._fetch_keyed_apis()
        raw_articles.extend(api_articles)
        errors.extend(api_errors)
        if not raw_articles and errors:
            # ProviderResult.error is capped at 1000 chars; many failing feeds
            # can exceed it, so truncate instead of raising ValidationError.
            return self._result(ContractStatus.FAILED, error="; ".join(errors)[:1000])

        unique = _deduplicate(raw_articles)
        relevant = [article for article in unique if _gold_relevance(article) >= _RELEVANCE_THRESHOLD]
        if len(unique) != len(raw_articles):
            logger.info("RSSNewsProvider: dedup removed %d duplicates", len(raw_articles) - len(unique))
        if len(relevant) != len(unique):
            logger.info(
                "RSSNewsProvider: relevance kept %d/%d articles",
                len(relevant), len(unique),
            )
        events = tuple(
            NewsEventSnapshot(
                headline=article["title"],
                url=article["url"],
                date=article["date"],
                source=article["source"],
            )
            for article in relevant
        )
        return self._result(ContractStatus.SUCCESS, data=events)

    def _fetch_keyed_apis(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Best-effort pulls from key-gated news APIs ported from v2.

        Each API is optional: a missing key just contributes an error note, and
        the keyless RSS feeds (or another API) keep the chain alive.
        """
        articles: list[dict[str, Any]] = []
        errors: list[str] = []
        for api in self._KEYED_APIS:
            api_key = os.getenv(api["env_var"])
            if not api_key:
                errors.append(f"{api['name']}: Required environment variable {api['env_var']} is not set.")
                continue
            for api_query in api["queries"]:
                status, payload, error = self._get_json(
                    api["endpoint"],
                    {api["api_key_param"]: api_key, "search": api_query},
                )
                if status != ContractStatus.SUCCESS:
                    errors.append(f"{api['name']}: {error}")
                    continue
                articles.extend(self._parse_api_items(api, payload))
        return articles, errors

    def _parse_api_items(
        self,
        api: dict[str, Any],
        payload: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        items = payload
        for key in api["items_path"]:
            if not isinstance(items, dict):
                return []
            items = items.get(key)
        if not isinstance(items, list):
            return []
        field_map = api["field_map"]
        parsed: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get(field_map["title"]) or "").strip()
            url = str(item.get(field_map["url"]) or "").strip()
            if not title or not url:
                continue
            date = _safe_parse_date(item.get(field_map["date"]))
            if date is None:
                continue
            source = str(item.get(field_map["source"]) or "").strip()
            parsed.append(
                {
                    "title": title[:500],
                    "url": url[:1000],
                    "description": str(item.get(field_map["description"]) or "").strip()[:500],
                    "date": date,
                    "source": source or api["name"],
                }
            )
        return parsed

    def _parse_rss(self, xml_text: str) -> list[dict[str, Any]]:
        articles: list[dict[str, Any]] = []
        root = ElementTree.fromstring(xml_text)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            if not title or not url:
                continue
            source_element = item.find("source")
            source_name = (source_element.text or "").strip() if source_element is not None else ""
            articles.append(
                {
                    "title": title[:500],
                    "url": url[:1000],
                    "description": description[:500],
                    "date": _parse_rss_date(pub_date),
                    "source": source_name or "google_news",
                }
            )
        return articles


def _parse_rss_date(value: str):
    if value:
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (ValueError, TypeError):
            pass
    return parse_datetime(value)


def _safe_parse_date(value: Any):
    """ISO/RFC timestamps from keyed APIs; None when unparseable so the item is
    skipped instead of crashing the whole chain."""
    if not value:
        return None
    try:
        parsed = parse_datetime(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def _gold_relevance(article: dict[str, Any]) -> float:
    text = " ".join(
        (article.get("title", ""), article.get("description", ""))
    ).lower()
    direct = sum(1 for signal in _DIRECT_SIGNALS if _signal_hits(signal, text))
    macro = sum(1 for signal in _MACRO_SIGNALS if _signal_hits(signal, text))
    geo = sum(1 for signal in _GEO_SIGNALS if _signal_hits(signal, text))
    haven = sum(1 for signal in _SAFE_HAVEN_SIGNALS if _signal_hits(signal, text))
    score = 0.0
    score += min(direct * 0.25, 0.5)
    score += min(macro * 0.1, 0.3)
    score += min(geo * 0.1, 0.25)
    score += min(haven * 0.15, 0.2)
    if "gold" in article.get("title", "").lower():
        score += 0.15
    return min(1.0, round(score, 3))


def _signal_hits(signal: str, text: str) -> bool:
    """Word-boundary match so short signals like 'war' or 'fed' don't fire on
    substrings such as 'warm' or 'confederate'."""
    return re.search(rf"\b{re.escape(signal)}\b", text) is not None


def _deduplicate(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    seen_fingerprints: set[str] = set()
    unique: list[dict[str, Any]] = []
    for article in articles:
        url = article.get("url", "")
        if url and url in seen_urls:
            continue
        fingerprint = _title_fingerprint(article.get("title", ""))
        if fingerprint in seen_fingerprints:
            continue
        if url:
            seen_urls.add(url)
        seen_fingerprints.add(fingerprint)
        unique.append(article)
    return unique


def _title_fingerprint(title: str) -> str:
    normalized = "".join(
        char for char in title.lower().strip() if char.isalnum() or char == " "
    )
    normalized = " ".join(normalized.split())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()
