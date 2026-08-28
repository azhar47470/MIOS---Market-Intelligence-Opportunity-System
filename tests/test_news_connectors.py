"""Tests for the v2 news-engine port: 15-connector layer, FeedManager,
gold-relevance/topic stages, connector provider, repository chain, and
publisher-tier verification."""

import asyncio
import json
from datetime import UTC, datetime

from app.application.cache import InMemoryCacheRepository
from app.application.events.verifier import CrossSourceVerifier
from app.application.http import HttpResponse
from app.domain.common import ContractStatus
from app.domain.intelligence import MarketEvent
from app.domain.market_data import DataProviderId
from app.domain.provider_snapshots import NewsEventSnapshot
from app.infrastructure.config_loader import load_platform_config
from app.infrastructure.news.discovery_apis import (
    TheNewsAPIConnector,
    WorldNewsAPIConnector,
)
from app.infrastructure.news.feed_manager import FeedManager
from app.infrastructure.news.finnhub import FinnhubConnector
from app.infrastructure.news.google_rss import GoogleRSSConnector
from app.infrastructure.news.marketaux import MarketAuxConnector
from app.infrastructure.news.relevance import GoldRelevanceEngine
from app.infrastructure.news.reuters import ReutersConnector
from app.infrastructure.news.topics import TopicClassifier
from app.infrastructure.providers.gdelt_provider import GDELTProvider
from app.infrastructure.providers.news_connector_provider import NewsConnectorProvider
from app.infrastructure.repositories.provider_repositories import ProviderNewsEventRepository

_RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test Feed</title>
<item>
  <title>Gold hits record as Fed rate-cut bets grow</title>
  <link>https://example.test/gold-1</link>
  <description>Investors piled into bullion on monetary policy expectations.</description>
  <pubDate>Tue, 14 Jul 2026 10:30:00 GMT</pubDate>
  <source url="https://reuters.com">Reuters</source>
</item>
<item>
  <title>Inflation data due this week</title>
  <link>https://example.test/inflation</link>
  <description>CPI release will shape the rate outlook.</description>
  <pubDate>Tue, 14 Jul 2026 09:00:00 GMT</pubDate>
</item>
</channel></rss>"""

_IRRELEVANT_RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Test Feed</title>
<item>
  <title>Apple unveils new phone</title>
  <link>https://example.test/apple</link>
  <description>Consumer electronics announcement.</description>
  <pubDate>Tue, 14 Jul 2026 10:30:00 GMT</pubDate>
</item>
</channel></rss>"""


class FakeHttpClient:
    def __init__(self, responses: tuple[HttpResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests = []

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        self.requests.append({"url": url, "params": params or {}, "headers": headers or {}})
        return self._responses.pop(0)


def _json_response(payload) -> HttpResponse:
    return HttpResponse(status_code=200, body=json.dumps(payload))


def test_parse_date_handles_rfc3339_fractional_and_empty():
    http = FakeHttpClient((HttpResponse(status_code=200, body=_RSS_XML),))
    connector = ReutersConnector(http)

    parsed = connector._parse_date("2026-07-14T10:30:00.123456+00:00")
    assert parsed.startswith("2026-07-14T10:30:00")

    parsed_z = connector._parse_date("2026-07-14T10:30:00.123456Z")
    assert parsed_z.startswith("2026-07-14T10:30:00")

    rfc822 = connector._parse_date("Tue, 14 Jul 2026 10:30:00 GMT")
    assert rfc822.startswith("2026-07-14T10:30:00")

    plain = connector._parse_date("2026-07-14")
    assert plain.startswith("2026-07-14T00:00:00")


def test_reuters_connector_parses_rss_items():
    http = FakeHttpClient((HttpResponse(status_code=200, body=_RSS_XML),))
    connector = ReutersConnector(http)

    result = connector.fetch()

    assert result.connector_name == "reuters"
    assert result.articles_fetched == 2
    assert result.errors == []
    first = result.articles[0]
    assert first.title == "Gold hits record as Fed rate-cut bets grow"
    assert first.source == "reuters"
    assert first.url == "https://example.test/gold-1"
    assert first.published_at.startswith("2026-07-14")
    assert first.tier == 1 if hasattr(first, "tier") else True
    assert connector.tier == 1
    assert connector.trust_score == 10.0
    assert http.requests[0]["url"].startswith("https://news.google.com/rss/search")


def test_google_rss_connector_preserves_publisher_and_runs_all_queries():
    http = FakeHttpClient(
        (
            HttpResponse(status_code=200, body=_RSS_XML),
            HttpResponse(status_code=200, body=_RSS_XML),
            HttpResponse(status_code=200, body=_RSS_XML),
            HttpResponse(status_code=200, body=_RSS_XML),
            HttpResponse(status_code=200, body=_RSS_XML),
        )
    )
    connector = GoogleRSSConnector(http)

    result = connector.fetch()

    assert result.articles_fetched == 10
    assert len(http.requests) == 5
    assert all("news.google.com" in request["url"] for request in http.requests)
    assert result.articles[0].source == "Reuters"


def test_finnhub_connector_fetches_news_and_skips_without_key(monkeypatch):
    http = FakeHttpClient(
        (
            _json_response(
                [
                    {"headline": "Gold steady ahead of Fed", "summary": "Markets watch policy.",
                     "url": "https://example.test/fh", "datetime": 1784197800},
                ]
            ),
            _json_response([]),
        )
    )
    monkeypatch.setenv("FINNHUB_API_KEY", "test-finnhub-key")
    connector = FinnhubConnector(http)

    result = connector.fetch()

    assert result.articles_fetched == 1
    assert result.articles[0].title == "Gold steady ahead of Fed"
    assert result.articles[0].source == "finnhub"
    assert connector.tier == 2
    assert connector.trust_score == 8.5
    assert len(http.requests) == 2

    monkeypatch.delenv("FINNHUB_API_KEY")
    no_key = FinnhubConnector(http)
    empty = no_key.fetch()
    assert empty.articles == []
    assert "No FINNHUB_API_KEY" in empty.errors


def test_marketaux_connector_extracts_symbols(monkeypatch):
    http = FakeHttpClient(
        (
            _json_response(
                {
                    "data": [
                        {
                            "title": "Central banks buy gold",
                            "description": "Reserve diversification continues.",
                            "url": "https://example.test/ma",
                            "published_at": "2026-07-14T08:00:00+00:00",
                            "entities": {"symbols": [{"symbol": "GOLD"}]},
                        }
                    ]
                }
            ),
        )
    )
    monkeypatch.setenv("MARKETAUX_API_KEY", "test-marketaux-key")
    connector = MarketAuxConnector(http)

    result = connector.fetch()

    assert result.articles_fetched == 1
    assert result.articles[0].symbols == ["GOLD"]
    assert connector.tier == 2


def test_thenewsapi_and_worldnewsapi_connectors_parse_items(monkeypatch):
    http = FakeHttpClient(
        (
            _json_response(
                {
                    "data": [
                        {
                            "title": "Gold rally continues",
                            "description": "Safe-haven demand drives prices.",
                            "url": "https://example.test/tna",
                            "published_at": "2026-07-14T08:00:00+00:00",
                            "source": "ExampleWire",
                        }
                    ]
                }
            ),
        )
    )
    monkeypatch.setenv("THENEWSAPI_KEY", "test-thenewsapi-key")
    connector = TheNewsAPIConnector(http)
    result = connector.fetch()
    assert result.articles_fetched == 1
    assert result.articles[0].source == "ExampleWire"
    assert connector.tier == 4

    http2 = FakeHttpClient(
        (
            _json_response(
                {
                    "news": [
                        {
                            "title": "Gold and central banks",
                            "summary": "Policy outlook supports bullion.",
                            "url": "https://example.test/wna",
                            "publish_date": "2026-07-14T08:00:00+00:00",
                            "source_name": "WireService",
                        }
                    ]
                }
            ),
        )
    )
    monkeypatch.setenv("WORLDNEWSAPI_KEY", "test-worldnewsapi-key")
    connector2 = WorldNewsAPIConnector(http2)
    result2 = connector2.fetch()
    assert result2.articles_fetched == 1
    assert result2.articles[0].source == "WireService"
    assert connector2.tier == 4


def test_topic_classifier_detects_v2_twenty_topic_vocab():
    classifier = TopicClassifier()
    article = _article(
        "Fed holds rates as inflation cools and Middle East conflict escalates",
        "summary",
        "Central bank monetary policy and war risk drive gold demand.",
    )

    topics = classifier.classify(article)

    assert "central_bank" in topics
    assert "inflation" in topics
    assert "war" in topics


def test_gold_relevance_engine_scores_and_filters():
    engine = GoldRelevanceEngine()
    gold_article = _article(
        "Gold price jumps on Fed rate-cut bets",
        "Bullion gains as monetary policy eases.",
        "Real yields fall and dollar weakens.",
    )
    apple_article = _article("Apple unveils new phone", "Consumer electronics.", "Camera specs.")

    assert engine.score(gold_article) >= 0.1
    assert engine.score(apple_article) < 0.1


def test_feed_manager_skips_unhealthy_connector_and_serves_cache():
    http = FakeHttpClient(
        (
            HttpResponse(status_code=200, body=_RSS_XML),
            HttpResponse(status_code=500, body="boom"),
            HttpResponse(status_code=500, body="boom"),
            HttpResponse(status_code=500, body="boom"),
        )
    )
    connector = ReutersConnector(http)
    manager = FeedManager([connector])

    first = manager.fetch_all()
    assert len(first) == 2
    assert manager.health["reuters"].consecutive_failures == 0

    for _ in range(3):
        manager.fetch_all()
    assert manager.health["reuters"].consecutive_failures == 3
    assert not manager.health["reuters"].is_healthy

    cached = manager.fetch_all()
    assert len(cached) == 2, "unhealthy connector should serve cached articles"
    report = manager.get_health_report()["reuters"]
    assert report["healthy"] is False
    assert report["consecutive_failures"] == 3


def test_connector_provider_converts_to_snapshots_and_filters_relevance():
    http = FakeHttpClient((HttpResponse(status_code=200, body=_RSS_XML),))
    provider = NewsConnectorProvider(http, feed_manager=FeedManager([ReutersConnector(http)]))

    result = asyncio.run(provider.fetch_all())

    assert result.status == ContractStatus.SUCCESS
    assert result.provider == "news_connectors"
    assert result.data is not None
    assert len(result.data) == 2
    snapshot: NewsEventSnapshot = result.data[0]
    assert snapshot.headline == "Gold hits record as Fed rate-cut bets grow"
    assert snapshot.source == "reuters"
    assert snapshot.date.tzinfo is not None
    assert snapshot.date.astimezone(UTC).date().isoformat() == "2026-07-14"


def test_connector_provider_relevance_filter_drops_irrelevant_feed():
    http = FakeHttpClient(
        (HttpResponse(status_code=200, body=_IRRELEVANT_RSS_XML),)
    )
    provider = NewsConnectorProvider(http, feed_manager=FeedManager([ReutersConnector(http)]))

    result = asyncio.run(provider.fetch_all())

    assert result.status == ContractStatus.SUCCESS
    assert result.data == ()


def test_news_repository_uses_connectors_first_and_skips_gdelt(monkeypatch, tmp_path):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("FINNHUB_API_KEY", "test-finnhub-key")
    http = FakeHttpClient((HttpResponse(status_code=200, body=_RSS_XML),))
    GDELTProvider._last_request_at = None
    repository = ProviderNewsEventRepository(
        provider=GDELTProvider(
            config.providers[DataProviderId.GDELT],
            http,
            cooldown_state_path=tmp_path / "gdelt_cooldown.json",
        ),
        cache=InMemoryCacheRepository(),
        connector_provider=NewsConnectorProvider(http, feed_manager=FeedManager([ReutersConnector(http)])),
        fallback_provider=None,
        rss_provider=None,
    )

    bundle = asyncio.run(repository.latest("gold"))

    assert bundle.events.status == ContractStatus.SUCCESS
    assert bundle.events.provider == "news_connectors"
    assert len(bundle.events.data or ()) == 2
    assert len(http.requests) == 1, "GDELT must not be called when connectors succeed"
    GDELTProvider._last_request_at = None


def test_news_repository_falls_back_to_gdelt_when_connectors_fail(monkeypatch, tmp_path):
    config = load_platform_config("config/platform.json")
    http = FakeHttpClient(
        (
            HttpResponse(status_code=500, body="connector down"),
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
        cache=InMemoryCacheRepository(),
        connector_provider=NewsConnectorProvider(http, feed_manager=FeedManager([ReutersConnector(http)])),
        fallback_provider=None,
        rss_provider=None,
    )

    bundle = asyncio.run(repository.latest("gold"))

    assert bundle.events.status == ContractStatus.SUCCESS
    assert bundle.events.provider == DataProviderId.GDELT.value
    assert len(bundle.events.data or ()) == 1
    GDELTProvider._last_request_at = None


def test_news_repository_falls_through_to_gdelt_when_connectors_succeed_but_empty(
    monkeypatch, tmp_path
):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("FINNHUB_API_KEY", "test-finnhub-key")
    http = FakeHttpClient(
        (
            HttpResponse(status_code=200, body=_IRRELEVANT_RSS_XML),
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
        cache=InMemoryCacheRepository(),
        connector_provider=NewsConnectorProvider(http, feed_manager=FeedManager([ReutersConnector(http)])),
        fallback_provider=None,
        rss_provider=None,
    )

    bundle = asyncio.run(repository.latest("gold"))

    # A healthy-but-empty connector layer must not shadow the fallback chain.
    assert bundle.events.status == ContractStatus.SUCCESS
    assert bundle.events.provider == DataProviderId.GDELT.value
    assert len(bundle.events.data or ()) == 1
    GDELTProvider._last_request_at = None


def test_verifier_resolves_v2_publisher_tiers_and_connector_names():
    verifier = CrossSourceVerifier()

    fed_financial = MarketEvent(
        event_id="e1",
        title="Fed holds rates",
        summary="",
        sources=("fed", "financial times"),
        confidence=0.5,
    )
    cbs_zero = MarketEvent(
        event_id="e2",
        title="Gold rally",
        summary="",
        sources=("CBS News", "Zero Hedge"),
        confidence=0.5,
    )
    unknown = MarketEvent(
        event_id="e3",
        title="Gold rally",
        summary="",
        sources=("RandomAggregator", "AnotherAggregator"),
        confidence=0.5,
    )

    verified = verifier.verify((fed_financial, cbs_zero, unknown))

    assert verified[0].best_tier == 1
    assert verified[0].is_confirmed is True
    assert verified[1].best_tier == 2, "CBS News should resolve to tier 2 via v2 publisher list"
    assert verified[2].best_tier == 5


def _article(title: str, summary: str, content: str):
    from app.infrastructure.news.article import Article

    return Article(
        title=title,
        summary=summary,
        content=content,
        source="test",
        url="https://example.test/a",
        published_at="2026-07-14T08:00:00+00:00",
    )