import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.application.cache import InMemoryCacheRepository
from app.application.market_data_collector import RepositoryBackedMarketDataCollector
from app.application.http import HttpResponse
from app.domain.common import ContractStatus
from app.domain.market_data import DataProviderId
from app.domain.provider_snapshots import NewsEventSnapshot
from app.domain.source_data import (
    CalendarSourceBundle,
    InstitutionalSourceBundle,
    MarketSourceBundle,
    NewsSourceBundle,
    SourceReadResult,
)
from app.infrastructure.config_loader import load_platform_config
from app.infrastructure.providers.gdelt_provider import GDELTProvider
from app.infrastructure.providers.newsapi_provider import NewsAPIProvider
from app.infrastructure.providers.rss_news_provider import RSSNewsProvider
from app.infrastructure.repositories.provider_repositories import (
    ProviderNewsEventRepository,
)

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item>
<title>Gold price steadies as investors await Fed rate decision</title>
<link>https://www.reuters.com/markets/gold-price-steadies</link>
<description>Gold held steady on Tuesday as investors awaited the central bank decision.</description>
<pubDate>Tue, 04 Aug 2026 06:00:00 GMT</pubDate>
<source url="https://www.reuters.com">Reuters</source>
</item>
<item>
<title>Ten summer recipes for fresh pasta</title>
<link>https://example.com/recipes</link>
<description>Easy pasta dishes for warm evenings.</description>
<pubDate>Tue, 04 Aug 2026 05:00:00 GMT</pubDate>
<source url="https://example.com">Example News</source>
</item>
</channel></rss>"""


class FakeHttpClient:
    def __init__(self, responses: tuple[HttpResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests = []

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        self.requests.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self._responses.pop(0)


class FakeMarketRepository:
    async def latest(self) -> MarketSourceBundle:
        return MarketSourceBundle(
            gold_price=SourceReadResult(status=ContractStatus.NO_DATA),
            gold_bars=SourceReadResult(status=ContractStatus.NO_DATA, data=()),
            dxy=SourceReadResult(status=ContractStatus.NO_DATA),
        )


class FakeInstitutionalRepository:
    async def latest(self) -> InstitutionalSourceBundle:
        return InstitutionalSourceBundle(
            cot=SourceReadResult(status=ContractStatus.NO_DATA),
            gld=SourceReadResult(status=ContractStatus.NO_DATA),
        )


class FakeCalendarRepository:
    async def latest(self) -> CalendarSourceBundle:
        return CalendarSourceBundle(events=SourceReadResult(status=ContractStatus.NO_DATA, data=()))


class FakeMacroRepository:
    async def latest(self):
        return None


def _rss_provider(http: FakeHttpClient) -> RSSNewsProvider:
    config = load_platform_config("config/platform.json")
    return RSSNewsProvider(config.providers[DataProviderId.RSS_NEWS], http)


def test_rss_provider_parses_feeds_and_preserves_source_outlet(monkeypatch):
    monkeypatch.setattr(
        RSSNewsProvider, "_FEED_QUERIES", (("reuters_gold", "site:reuters.com gold"),)
    )
    provider = _rss_provider(FakeHttpClient((HttpResponse(status_code=200, body=SAMPLE_RSS),)))

    result = asyncio.run(provider.news_events("gold"))

    assert result.status == ContractStatus.SUCCESS
    assert result.provider == DataProviderId.RSS_NEWS.value
    assert result.data is not None
    assert len(result.data) == 1
    event = result.data[0]
    assert event.headline == "Gold price steadies as investors await Fed rate decision"
    assert event.url == "https://www.reuters.com/markets/gold-price-steadies"
    assert event.source == "Reuters"
    assert event.date.tzinfo is not None and event.date.utcoffset() is not None
    assert event.date.year == 2026


def test_rss_provider_deduplicates_identical_titles_and_urls(monkeypatch):
    duplicate_rss = SAMPLE_RSS.replace(
        "<link>https://www.reuters.com/markets/gold-price-steadies</link>",
        "<link>https://www.reuters.com/markets/duplicate-copy</link>",
    )
    duplicate_rss = duplicate_rss.replace(
        "</channel></rss>",
        """<item>
<title>Gold price steadies as investors await Fed rate decision</title>
<link>https://www.reuters.com/markets/gold-price-steadies</link>
<description>Copy.</description>
<pubDate>Tue, 04 Aug 2026 05:30:00 GMT</pubDate>
<source url="https://www.reuters.com">Reuters</source>
</item>
</channel></rss>""",
    )
    monkeypatch.setattr(
        RSSNewsProvider, "_FEED_QUERIES", (("reuters_gold", "site:reuters.com gold"),)
    )
    provider = _rss_provider(FakeHttpClient((HttpResponse(status_code=200, body=duplicate_rss),)))

    result = asyncio.run(provider.news_events("gold"))

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert len(result.data) == 1


def test_rss_provider_fails_when_all_feeds_error(monkeypatch):
    monkeypatch.setattr(
        RSSNewsProvider, "_FEED_QUERIES", (("reuters_gold", "site:reuters.com gold"),)
    )
    provider = _rss_provider(
        FakeHttpClient((HttpResponse(status_code=503, body="Google News unavailable"),))
    )

    result = asyncio.run(provider.news_events("gold"))

    assert result.status == ContractStatus.FAILED
    assert result.data is None
    assert "reuters_gold" in (result.error or "")


def _json(payload):
    import json

    return json.dumps(payload)


def _marketaux_payload(title, url, source="Reuters", description="Gold market commentary."):
    return _json(
        {
            "data": [
                {
                    "title": title,
                    "url": url,
                    "description": description,
                    "published_at": "2026-07-12T08:30:00+00:00",
                    "source": source,
                }
            ]
        }
    )


def _thenewsapi_payload(title, url, source="Bloomberg", description="Central bank policy update."):
    return _json(
        {
            "data": [
                {
                    "title": title,
                    "url": url,
                    "description": description,
                    "published_at": "2026-07-12T09:00:00+00:00",
                    "source": source,
                }
            ]
        }
    )


def _worldnewsapi_payload(title, url, source="Kitco News", description="Geopolitical risk lifts bullion."):
    return _json(
        {
            "news": [
                {
                    "title": title,
                    "url": url,
                    "summary": description,
                    "publish_date": "2026-07-12T10:00:00+00:00",
                    "source_name": source,
                }
            ]
        }
    )


def test_keyed_apis_merged_into_rss_stream(monkeypatch):
    monkeypatch.setattr(RSSNewsProvider, "_FEED_QUERIES", ())
    monkeypatch.setenv("MARKETAUX_API_KEY", "test-marketaux-key")
    monkeypatch.setenv("THENEWSAPI_KEY", "test-thenewsapi-key")
    monkeypatch.setenv("WORLDNEWSAPI_KEY", "test-worldnewsapi-key")
    http = FakeHttpClient(
        (
            HttpResponse(status_code=200, body=_marketaux_payload(
                "Gold price steadies as investors await Fed decision",
                "https://api.marketaux.com/1",
            )),
            HttpResponse(status_code=200, body=_marketaux_payload(
                "Inflation report due Wednesday",
                "https://api.marketaux.com/2",
                source="MarketWatch",
            )),
            HttpResponse(status_code=200, body=_marketaux_payload(
                "Gold price steadies as investors await Fed decision",
                "https://api.marketaux.com/3",
                source="MarketWatch",
            )),
            HttpResponse(status_code=200, body=_marketaux_payload(
                "Central banks keep buying gold",
                "https://api.marketaux.com/4",
                source="Kitco News",
            )),
            HttpResponse(status_code=200, body=_thenewsapi_payload(
                "Fed rate path in focus as gold holds gains",
                "https://api.thenewsapi.com/1",
            )),
            HttpResponse(status_code=200, body=_thenewsapi_payload(
                "Inflation cools but gold demand persists",
                "https://api.thenewsapi.com/2",
            )),
            HttpResponse(status_code=200, body=_thenewsapi_payload(
                "Best laptop deals this week",
                "https://api.thenewsapi.com/3",
                source="Tech Weekly",
                description="Weekend tech roundup.",
            )),
            HttpResponse(status_code=200, body=_worldnewsapi_payload(
                "Gold near record high on safe-haven demand",
                "https://api.worldnewsapi.com/1",
            )),
            HttpResponse(status_code=200, body=_worldnewsapi_payload(
                "Treasury yields retreat as inflation fears ease",
                "https://api.worldnewsapi.com/2",
                source="Investing.com",
            )),
            HttpResponse(status_code=200, body=_worldnewsapi_payload(
                "Cookbook author shares weeknight dinners",
                "https://api.worldnewsapi.com/3",
                source="Food Weekly",
                description="Easy dinner recipes.",
            )),
        )
    )
    provider = _rss_provider(http)

    result = asyncio.run(provider.news_events("gold"))

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert len(result.data) == 7
    headlines = {event.headline for event in result.data}
    assert "Gold price steadies as investors await Fed decision" in headlines
    assert "Best laptop deals this week" not in headlines
    assert "Cookbook author shares weeknight dinners" not in headlines
    assert len(http.requests) == 10
    marketaux_params = http.requests[0]["params"]
    assert marketaux_params["api_token"] == "test-marketaux-key"
    assert marketaux_params["search"] == "gold"
    assert "api.marketaux.com" in http.requests[0]["url"]
    assert http.requests[7]["params"]["api-key"] == "test-worldnewsapi-key"
    sources = {event.source for event in result.data}
    assert "Reuters" in sources
    assert "Kitco News" in sources


def test_keyed_apis_skipped_when_keys_missing(monkeypatch):
    monkeypatch.setattr(RSSNewsProvider, "_FEED_QUERIES", ())
    provider = _rss_provider(FakeHttpClient(()))

    result = asyncio.run(provider.news_events("gold"))

    assert result.status == ContractStatus.FAILED
    assert result.data is None
    assert "MARKETAUX_API_KEY" in (result.error or "")
    assert "THENEWSAPI_KEY" in (result.error or "")
    assert "WORLDNEWSAPI_KEY" in (result.error or "")


def test_keyed_api_items_skipped_when_date_unparseable(monkeypatch):
    monkeypatch.setattr(RSSNewsProvider, "_FEED_QUERIES", ())
    monkeypatch.setattr(
        RSSNewsProvider,
        "_KEYED_APIS",
        (
            {
                "name": "marketaux",
                "env_var": "MARKETAUX_API_KEY",
                "api_key_param": "api_token",
                "endpoint": "marketaux_all",
                "queries": ("gold",),
                "items_path": ("data",),
                "field_map": {
                    "title": "title",
                    "description": "description",
                    "url": "url",
                    "date": "published_at",
                    "source": "source",
                },
            },
        ),
    )
    monkeypatch.setenv("MARKETAUX_API_KEY", "test-marketaux-key")
    payload = {
        "data": [
            {
                "title": "Gold extends rally",
                "url": "https://api.marketaux.com/gold-rally",
                "published_at": "not-a-date",
                "source": "Reuters",
            },
            {
                "title": "",
                "url": "https://api.marketaux.com/empty-title",
                "published_at": "2026-07-12T08:30:00+00:00",
                "source": "Reuters",
            },
        ]
    }
    provider = _rss_provider(
        FakeHttpClient((HttpResponse(status_code=200, body=_json(payload)),))
    )

    result = asyncio.run(provider.news_events("gold"))

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data == ()


def test_news_repository_uses_keyed_apis_with_keys(monkeypatch, tmp_path):
    config = load_platform_config("config/platform.json")
    monkeypatch.setattr(RSSNewsProvider, "_FEED_QUERIES", ())
    monkeypatch.setenv("MARKETAUX_API_KEY", "test-marketaux-key")
    http = FakeHttpClient(
        (
            HttpResponse(status_code=503, body="GDELT unavailable"),
            HttpResponse(status_code=200, body=_marketaux_payload(
                "Gold price steadies as investors await Fed decision",
                "https://api.marketaux.com/1",
            )),
            HttpResponse(status_code=200, body=_marketaux_payload(
                "Central banks keep buying gold",
                "https://api.marketaux.com/4",
                source="Kitco News",
            )),
            HttpResponse(status_code=200, body=_marketaux_payload(
                "Fed rate path in focus as gold holds gains",
                "https://api.marketaux.com/5",
                source="Bloomberg",
            )),
            HttpResponse(status_code=200, body=_marketaux_payload(
                "Inflation report due Wednesday",
                "https://api.marketaux.com/6",
                source="MarketWatch",
            )),
        )
    )
    GDELTProvider._last_request_at = None
    repository = ProviderNewsEventRepository(
        provider=GDELTProvider(
            config.providers[DataProviderId.GDELT],
            http,
            cooldown_state_path=tmp_path / "gdelt_cooldown.json",
        ),
        rss_provider=RSSNewsProvider(config.providers[DataProviderId.RSS_NEWS], http),
        cache=InMemoryCacheRepository(),
    )

    bundle = asyncio.run(repository.latest("gold"))

    assert bundle.events.status == ContractStatus.SUCCESS
    assert bundle.events.provider == DataProviderId.RSS_NEWS.value
    assert bundle.events.used_cache is False
    assert bundle.events.data is not None
    assert len(bundle.events.data) == 4
    assert len(http.requests) == 5
    assert "api.gdeltproject.org" in http.requests[0]["url"]
    assert "api.marketaux.com" in http.requests[1]["url"]
    GDELTProvider._last_request_at = None


def test_news_repository_falls_back_to_rss_when_gdelt_and_newsapi_fail(monkeypatch, tmp_path):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("NEWSAPI_KEY", "test-newsapi-key")
    http = FakeHttpClient(
        (
            HttpResponse(status_code=503, body="GDELT unavailable"),
            HttpResponse(status_code=503, body="NewsAPI unavailable"),
            HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
            HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
            HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
                HttpResponse(status_code=200, body=SAMPLE_RSS),
            HttpResponse(status_code=503, body="GDELT unavailable"),
            HttpResponse(status_code=503, body="NewsAPI unavailable"),
        )
    )
    GDELTProvider._last_request_at = None
    repository = ProviderNewsEventRepository(
        provider=GDELTProvider(
            config.providers[DataProviderId.GDELT],
            http,
            cooldown_state_path=tmp_path / "gdelt_cooldown.json",
        ),
        fallback_provider=NewsAPIProvider(config.providers[DataProviderId.NEWSAPI], http),
        rss_provider=RSSNewsProvider(config.providers[DataProviderId.RSS_NEWS], http),
        cache=InMemoryCacheRepository(),
    )

    first_bundle = asyncio.run(repository.latest("gold"))
    second_bundle = asyncio.run(repository.latest("gold"))

    assert first_bundle.events.status == ContractStatus.SUCCESS
    assert first_bundle.events.provider == DataProviderId.RSS_NEWS.value
    assert first_bundle.events.data is not None
    assert first_bundle.events.data[0].headline == (
        "Gold price steadies as investors await Fed rate decision"
    )
    assert first_bundle.events.data[0].source == "Reuters"
    assert second_bundle.events.status == ContractStatus.SUCCESS
    assert second_bundle.events.provider == DataProviderId.RSS_NEWS.value
    assert second_bundle.events.used_cache is True
    assert len(http.requests) == 10
    assert "news.google.com" in http.requests[2]["url"]
    assert http.requests[2]["params"]["q"] == "site:reuters.com gold OR \"federal reserve\" OR inflation"
    GDELTProvider._last_request_at = None


def test_news_repository_skips_rss_when_gdelt_succeeds(monkeypatch, tmp_path):
    config = load_platform_config("config/platform.json")
    http = FakeHttpClient(
        (
            HttpResponse(
                status_code=200,
                body=(
                    '{"articles": [{"title": "Gold market update", '
                    '"url": "https://example.com/gdelt-gold", '
                    '"seendate": "2026-07-12T08:30:00+00:00"}]}'
                ),
            ),
        )
    )
    GDELTProvider._last_request_at = None
    repository = ProviderNewsEventRepository(
        provider=GDELTProvider(
            config.providers[DataProviderId.GDELT],
            http,
            cooldown_state_path=tmp_path / "gdelt_cooldown.json",
        ),
        rss_provider=RSSNewsProvider(config.providers[DataProviderId.RSS_NEWS], http),
        cache=InMemoryCacheRepository(),
    )

    bundle = asyncio.run(repository.latest("gold"))

    assert bundle.events.status == ContractStatus.SUCCESS
    assert bundle.events.provider == DataProviderId.GDELT.value
    assert len(http.requests) == 1


def test_collector_preserves_rss_source_outlet():
    class FakeRssNewsRepository:
        async def latest(self, query: str) -> NewsSourceBundle:
            return NewsSourceBundle(
                events=SourceReadResult(
                    status=ContractStatus.SUCCESS,
                    data=(
                        NewsEventSnapshot(
                            headline="Gold price steadies as investors await Fed rate decision",
                            url="https://www.reuters.com/markets/gold-price-steadies",
                            date=datetime(2026, 8, 4, 6, 0, tzinfo=UTC),
                            source="Reuters",
                        ),
                    ),
                    provider=DataProviderId.RSS_NEWS.value,
                )
            )

    collector = RepositoryBackedMarketDataCollector(
        market_repository=FakeMarketRepository(),
        institutional_repository=FakeInstitutionalRepository(),
        calendar_repository=FakeCalendarRepository(),
        news_repository=FakeRssNewsRepository(),
        macro_repository=FakeMacroRepository(),
    )

    snapshot, statuses = asyncio.run(collector.collect())

    assert statuses["repository_news"] == ContractStatus.SUCCESS
    assert snapshot.news_articles[0].provider == DataProviderId.RSS_NEWS
    assert snapshot.news_articles[0].source_name == "Reuters"
    assert snapshot.news_articles[0].title == (
        "Gold price steadies as investors await Fed rate decision"
    )
