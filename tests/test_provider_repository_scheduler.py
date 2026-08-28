import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.application.cache import InMemoryCacheRepository
from app.application.engines.geopolitical_engine import GeopoliticalIntelligenceEngine
from app.application.engines.news_engine import NewsIntelligenceEngine
from app.application.event_bus import InMemoryEventBus
from app.application.http import HttpResponse
from app.application.market_data_collector import RepositoryBackedMarketDataCollector
from app.domain.common import ContractStatus
from app.domain.events import EventType
from app.domain.market_data import DataProviderId, MarketSymbol, Timeframe
from app.domain.provider_snapshots import DXYSnapshot, EconomicEventSnapshot, NewsEventSnapshot
from app.domain.source_data import (
    CalendarSourceBundle,
    InstitutionalSourceBundle,
    MarketSourceBundle,
    NewsSourceBundle,
    SourceReadResult,
)
from app.infrastructure.config_loader import load_platform_config
from app.infrastructure.providers.base import ProviderBase
from app.infrastructure.providers.cot_provider import COTProvider
from app.infrastructure.providers.dxy_provider import DXYProvider
from app.infrastructure.providers.fred_calendar_provider import FREDCalendarProvider
from app.infrastructure.providers.gdelt_provider import GDELTProvider
from app.infrastructure.providers.gld_provider import GLDProvider
from app.infrastructure.providers.newsapi_provider import GOLD_RELEVANT_QUERY, NewsAPIProvider
from app.infrastructure.providers.twelve_data_provider import TwelveDataProvider
from app.infrastructure.repositories.provider_repositories import (
    ProviderCalendarRepository,
    ProviderInstitutionalRepository,
    ProviderMarketRepository,
    ProviderNewsEventRepository,
)
from app.scheduler.polling_scheduler import PollingScheduler


class FakeHttpClient:
    def __init__(self, responses: tuple[HttpResponse, ...]) -> None:
        self._responses = list(responses)
        self.requests = []

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        self.requests.append({"url": url, "params": params or {}, "headers": headers or {}})
        if not self._responses:
            from app.infrastructure.http.urllib_http_client import HttpResponse
            return HttpResponse(status_code=200, body='{"values": [{"datetime": "2026-07-02T00:00:00+00:00", "open": "2300", "high": "2360", "low": "2290", "close": "2350", "volume": "10000"}]}')
        return self._responses.pop(0)


class FakeSocrataCotHttpClient:
    def __init__(self) -> None:
        self.requests = []
        self._rows = [
            {
                "report_date_as_yyyy_mm_dd": "2026-06-30",
                "market_and_exchange_names": "MICRO GOLD - COMMODITY EXCHANGE INC.",
                "m_money_positions_long_all": "1331",
                "m_money_positions_short_all": "0",
            },
            {
                "report_date_as_yyyy_mm_dd": "2026-06-30",
                "market_and_exchange_names": "GOLD - COMMODITY EXCHANGE INC.",
                "m_money_positions_long_all": "180000",
                "m_money_positions_short_all": "90000",
            },
        ]

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        params = params or {}
        self.requests.append({"url": url, "params": params, "headers": headers or {}})
        if params.get("$where") == "market_and_exchange_names = 'GOLD - COMMODITY EXCHANGE INC.'":
            rows = [
                row
                for row in self._rows
                if row["market_and_exchange_names"] == "GOLD - COMMODITY EXCHANGE INC."
            ]
        else:
            rows = self._rows
        return HttpResponse(status_code=200, body=json.dumps(rows))


class FakeClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class FakeMarketRepository:
    async def latest(self) -> MarketSourceBundle:
        return MarketSourceBundle(
            gold_price=SourceReadResult(status=ContractStatus.NO_DATA),
            gold_bars=SourceReadResult(status=ContractStatus.NO_DATA, data=()),
            dxy=SourceReadResult(
                status=ContractStatus.SUCCESS,
                data=DXYSnapshot(
                    price=Decimal("120.8866"),
                    change=Decimal("-0.1693"),
                    previous_price=Decimal("121.0559"),
                    previous_timestamp=datetime(2026, 6, 25, tzinfo=UTC),
                    timestamp=datetime(2026, 6, 26, tzinfo=UTC),
                ),
                provider=DataProviderId.FRED.value,
            ),
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


class FakeFredCalendarRepository:
    async def latest(self) -> CalendarSourceBundle:
        return CalendarSourceBundle(
            events=SourceReadResult(
                status=ContractStatus.SUCCESS,
                data=(
                    EconomicEventSnapshot(
                        title="Consumer Price Index",
                        time=datetime(2026, 7, 15, tzinfo=UTC),
                        importance="unrated",
                        country="US",
                    ),
                ),
                provider=DataProviderId.FRED.value,
            )
        )


class FakeNewsRepository:
    async def latest(self, query: str) -> NewsSourceBundle:
        return NewsSourceBundle(events=SourceReadResult(status=ContractStatus.NO_DATA, data=()))


class FakeNewsApiRepository:
    async def latest(self, query: str) -> NewsSourceBundle:
        return NewsSourceBundle(
            events=SourceReadResult(
                status=ContractStatus.SUCCESS,
                data=(
                    NewsEventSnapshot(
                        headline="Gold demand rises amid policy uncertainty",
                        url="https://example.com/gold-demand",
                        date=datetime(2026, 7, 12, tzinfo=UTC),
                    ),
                ),
                provider=DataProviderId.NEWSAPI.value,
            )
        )


def test_cot_provider_exact_matches_main_gold_contract_and_returns_snapshot():
    config = load_platform_config("config/platform.json")
    http = FakeSocrataCotHttpClient()
    provider = COTProvider(config.providers[DataProviderId.CFTC_COT], http)

    result = asyncio.run(provider.latest_gold_positions())

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data.long_positions == 180000
    assert result.data.short_positions == 90000
    assert result.data.net_position == 90000
    assert "publicreporting.cftc.gov" in http.requests[0]["url"]
    assert "/resource/72hh-3qpy.json" in http.requests[0]["url"]
    assert (
        http.requests[0]["params"]["$where"]
        == "market_and_exchange_names = 'GOLD - COMMODITY EXCHANGE INC.'"
    )
    assert http.requests[0]["params"]["$order"] == "report_date_as_yyyy_mm_dd DESC"
    assert http.requests[0]["params"]["$limit"] == "1"


GLD_SAMPLE_JSON = """
{
  "data": {
    "close_usd": {"value": "US$ 382.13", "performance": 1, "date": "July 6, 2026"},
    "current_iopv_usd": {"value": "US$ 382.28", "performance": -1},
    "daily_volume": {"value": "3,835,594", "performance": -1, "date": "July 6, 2026"},
    "metal_entitlement": {"value": "0.091765", "date": "July 6, 2026"},
    "nav_share_usd": {"value": "US$ 379.99", "performance": 1, "date": "July 6, 2026"},
    "shares_outstanding": {"value": "351,200,000", "performance": 1, "date": "July 6, 2026"},
    "total_nav_usd": {"value": "US$ 133,453,392,018.02", "performance": 1, "date": "July 6, 2026"},
    "total_ounces": {"value": "32,240,810.93", "performance": 1, "date": "July 6, 2026"},
    "total_tonnes": {"value": "1,002.793", "performance": 1, "date": "July 6, 2026"},
    "spot_bid_usd": {"value": "US$ 4,165.65", "performance": 1, "date": "July 6, 2026"}
  },
  "metadata": {
    "dataOwner": "World Gold Trust Services LLC",
    "maintainedBy": {"name": "542 Digital", "url": "https://542.digital/"},
    "license": "Proprietary",
    "disclaimer": "Proprietary data. Redistribution is prohibited."
  },
  "system": {"request_time": "2026-07-06 22:14:00", "response_time_ms": 6.99}
}
"""


def test_gld_provider_parses_live_json_contract_and_headers():
    config = load_platform_config("config/platform.json")
    http = FakeHttpClient((HttpResponse(status_code=200, body=GLD_SAMPLE_JSON),))
    provider = GLDProvider(config.providers[DataProviderId.SPDR_GLD], http)

    result = asyncio.run(provider.latest_flow())

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data.ounces == Decimal("32240810.93")
    assert result.data.total_tonnes == Decimal("1002.793")
    assert result.data.total_nav_usd == Decimal("133453392018.02")
    assert result.data.shares_outstanding == Decimal("351200000")
    assert result.data.field_dates["total_ounces"] == datetime(2026, 7, 6, tzinfo=UTC)
    assert http.requests[0]["params"] == {"product": "gld", "exchange": "NYSE", "lang": "en"}
    assert "Mozilla/5.0" in http.requests[0]["headers"]["User-Agent"]
    assert set(http.requests[0]["headers"]) == {"User-Agent"}


def test_gld_provider_reports_missing_required_field():
    config = load_platform_config("config/platform.json")
    http = FakeHttpClient((HttpResponse(status_code=200, body='{"data": {}, "system": {}}'),))
    provider = GLDProvider(config.providers[DataProviderId.SPDR_GLD], http)

    result = asyncio.run(provider.latest_flow())

    assert result.status == ContractStatus.INVALID_INPUT
    assert "Missing GLD field: total_ounces" in result.error


def test_gld_provider_logs_malformed_numeric_value(caplog):
    config = load_platform_config("config/platform.json")
    payload = json.loads(GLD_SAMPLE_JSON)
    payload["data"]["total_ounces"]["value"] = "N/A"
    http = FakeHttpClient((HttpResponse(status_code=200, body=json.dumps(payload)),))
    provider = GLDProvider(config.providers[DataProviderId.SPDR_GLD], http)

    with caplog.at_level(logging.WARNING, logger="mios.providers"):
        result = asyncio.run(provider.latest_flow())

    assert result.status == ContractStatus.INVALID_INPUT
    assert "invalid numeric value: N/A" in result.error
    assert "GLDProvider parsing failed" in caplog.text
    assert "invalid numeric value: N/A" in caplog.text


def test_dxy_provider_fred_fallback_preserves_previous_observation(monkeypatch):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("FRED_API_KEY", "test-fred-key")
    http = FakeHttpClient(
        (
            HttpResponse(
                status_code=200,
                body="""
                {
                  "observations": [
                    {"date": "2026-06-25", "value": "121.0559"},
                    {"date": "2026-06-26", "value": "120.8866"}
                  ]
                }
                """,
            ),
        )
    )
    provider = DXYProvider(
        fred_provider=ProviderBase(config.providers[DataProviderId.FRED], http),
    )

    result = asyncio.run(provider.latest_dxy())

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data.price == Decimal("120.8866")
    assert result.data.previous_price == Decimal("121.0559")
    assert result.data.change == Decimal("-0.1693")
    assert result.data.previous_timestamp < result.data.timestamp
    assert result.provider == DataProviderId.FRED.value


def test_market_data_collector_preserves_fred_dxy_observation_provider():
    collector = RepositoryBackedMarketDataCollector(
        market_repository=FakeMarketRepository(),
        institutional_repository=FakeInstitutionalRepository(),
        calendar_repository=FakeCalendarRepository(),
        news_repository=FakeNewsRepository(),
    )

    snapshot, _statuses = asyncio.run(collector.collect())

    assert snapshot.dxy_observations
    assert {observation.provider for observation in snapshot.dxy_observations} == {
        DataProviderId.FRED
    }


def test_market_data_collector_preserves_fred_calendar_event_provider():
    collector = RepositoryBackedMarketDataCollector(
        market_repository=FakeMarketRepository(),
        institutional_repository=FakeInstitutionalRepository(),
        calendar_repository=FakeFredCalendarRepository(),
        news_repository=FakeNewsRepository(),
    )

    snapshot, _statuses = asyncio.run(collector.collect())

    assert snapshot.economic_events
    assert snapshot.economic_events[0].provider == DataProviderId.FRED
    assert snapshot.economic_events[0].impact == "unrated"


def test_market_data_collector_preserves_newsapi_article_provider():
    collector = RepositoryBackedMarketDataCollector(
        market_repository=FakeMarketRepository(),
        institutional_repository=FakeInstitutionalRepository(),
        calendar_repository=FakeCalendarRepository(),
        news_repository=FakeNewsApiRepository(),
    )

    snapshot, statuses = asyncio.run(collector.collect())

    assert statuses["repository_news"] == ContractStatus.SUCCESS
    assert snapshot.news_articles[0].provider == DataProviderId.NEWSAPI
    assert snapshot.news_articles[0].source_name == DataProviderId.NEWSAPI.value
    assert snapshot.geopolitical_articles[0].provider == DataProviderId.NEWSAPI


def test_market_repository_derives_gold_quote_from_time_series(monkeypatch):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    http = FakeHttpClient(
        (
            HttpResponse(
                status_code=200,
                body="""
                {
                  "values": [
                    {
                      "datetime": "2026-07-02T13:00:00+00:00",
                      "open": "2340.00",
                      "high": "2355.00",
                      "low": "2338.00",
                      "close": "2350.50",
                      "volume": "1200"
                    },
                    {
                      "datetime": "2026-07-02T12:00:00+00:00",
                      "open": "2330.00",
                      "high": "2345.00",
                      "low": "2328.00",
                      "close": "2340.00",
                      "volume": "1100"
                    }
                  ]
                }
                """,
            ),
            HttpResponse(
                status_code=200,
                body="""
                {
                  "values": [
                    {
                      "datetime": "2026-07-02T08:00:00+00:00",
                      "open": "2320.00",
                      "high": "2350.00",
                      "low": "2310.00",
                      "close": "2340.00",
                      "volume": "5000"
                    }
                  ]
                }
                """,
            ),
        )
    )
    repository = ProviderMarketRepository(
        twelve_data_provider=TwelveDataProvider(config.providers[DataProviderId.TWELVE_DATA], http),
        dxy_provider=DXYProvider(fred_provider=None),
        cache=InMemoryCacheRepository(),
    )

    bundle = asyncio.run(repository.latest())

    assert bundle.gold_price.status == ContractStatus.SUCCESS
    assert bundle.gold_price.data is not None
    assert bundle.gold_price.data.price == Decimal("2350.50")
    assert bundle.gold_price.provider == DataProviderId.TWELVE_DATA.value
    assert all("/time_series" in request["url"] for request in http.requests)


def test_gdelt_provider_waits_for_request_cooldown(caplog, tmp_path):
    config = load_platform_config("config/platform.json")
    http = FakeHttpClient(
        (
            HttpResponse(status_code=200, body='{"articles": []}'),
            HttpResponse(status_code=200, body='{"articles": []}'),
        )
    )
    clock = FakeClock()
    GDELTProvider._last_request_at = None
    provider = GDELTProvider(
        config.providers[DataProviderId.GDELT],
        http,
        clock=clock,
        sleep=clock.sleep,
        cooldown_state_path=tmp_path / "gdelt_cooldown.json",
    )

    with caplog.at_level(logging.INFO, logger="mios.providers"):
        asyncio.run(provider.news_events("gold"))
        asyncio.run(provider.news_events("gold"))

    assert len(http.requests) == 2
    assert clock.sleeps == [20.0]
    assert "GDELTProvider cooldown active" in caplog.text
    GDELTProvider._last_request_at = None


NEWSAPI_SAMPLE_JSON = """
{
  "status": "ok",
  "totalResults": 1,
  "articles": [
    {
      "source": {"id": "reuters", "name": "Reuters"},
      "author": "Reporter",
      "title": "Gold rises as investors weigh central bank policy",
      "description": "Investors sought fresh direction from policy signals.",
      "url": "https://example.com/gold-policy",
      "publishedAt": "2026-07-12T08:30:00Z",
      "content": "Article content"
    }
  ]
}
"""


def test_news_repository_falls_back_to_newsapi_and_reuses_30_minute_cache(monkeypatch, tmp_path):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("NEWSAPI_KEY", "test-newsapi-key")
    http = FakeHttpClient(
        (
            HttpResponse(status_code=503, body="GDELT unavailable"),
            HttpResponse(status_code=200, body=NEWSAPI_SAMPLE_JSON),
            HttpResponse(status_code=503, body="GDELT unavailable"),
        )
    )
    clock = FakeClock()
    GDELTProvider._last_request_at = None
    repository = ProviderNewsEventRepository(
        provider=GDELTProvider(
            config.providers[DataProviderId.GDELT],
            http,
            clock=clock,
            sleep=clock.sleep,
            cooldown_state_path=tmp_path / "gdelt_cooldown.json",
        ),
        fallback_provider=NewsAPIProvider(config.providers[DataProviderId.NEWSAPI], http),
        cache=InMemoryCacheRepository(),
        fallback_ttl_seconds=config.providers[DataProviderId.NEWSAPI]
        .endpoints["everything"]
        .cache_seconds,
    )

    first_bundle = asyncio.run(repository.latest('gold OR XAU/USD OR "gold price"'))
    second_bundle = asyncio.run(repository.latest('gold OR XAU/USD OR "gold price"'))

    assert first_bundle.events.status == ContractStatus.SUCCESS
    assert first_bundle.events.provider == DataProviderId.NEWSAPI.value
    assert first_bundle.events.data is not None
    assert (
        first_bundle.events.data[0].headline == "Gold rises as investors weigh central bank policy"
    )
    assert second_bundle.events.status == ContractStatus.SUCCESS
    assert second_bundle.events.provider == DataProviderId.NEWSAPI.value
    assert second_bundle.events.used_cache is True
    assert len(http.requests) == 3
    assert http.requests[1]["params"]["apiKey"] == "test-newsapi-key"
    assert http.requests[1]["params"]["q"] == GOLD_RELEVANT_QUERY
    assert http.requests[1]["params"]["pageSize"] == "20"
    assert clock.sleeps == [20.0]
    GDELTProvider._last_request_at = None


def test_news_repository_degrades_cleanly_when_gdelt_and_newsapi_fail(monkeypatch, tmp_path):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("NEWSAPI_KEY", "test-newsapi-key")
    http = FakeHttpClient(
        (
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
        cache=InMemoryCacheRepository(),
    )

    bundle = asyncio.run(repository.latest("gold"))
    news = NewsIntelligenceEngine().analyze(bundle.events.data or ())
    geopolitical = GeopoliticalIntelligenceEngine().analyze(bundle.events.data or ())

    assert bundle.events.status == ContractStatus.FAILED
    assert bundle.events.data is None
    assert bundle.events.error == "NewsAPI unavailable"
    assert news.status == ContractStatus.NO_DATA
    assert geopolitical.status == ContractStatus.NO_DATA
    assert "0 supportive and 0 adverse" in news.evidence[0].description
    assert "0 geopolitical risk cue(s)" in geopolitical.evidence[0].description
    GDELTProvider._last_request_at = None


def test_news_repository_does_not_call_newsapi_when_gdelt_succeeds(monkeypatch, tmp_path):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("NEWSAPI_KEY", "test-newsapi-key")
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
        fallback_provider=NewsAPIProvider(config.providers[DataProviderId.NEWSAPI], http),
        cache=InMemoryCacheRepository(),
    )

    bundle = asyncio.run(repository.latest("gold"))

    assert bundle.events.status == ContractStatus.SUCCESS
    assert bundle.events.provider == DataProviderId.GDELT.value
    assert len(http.requests) == 1
    assert "api.gdeltproject.org" in http.requests[0]["url"]
    GDELTProvider._last_request_at = None


def test_calendar_repository_reads_fred_release_dates_primary(monkeypatch):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("FRED_API_KEY", "test-fred-key")
    http = FakeHttpClient(
        (
            HttpResponse(
                status_code=200,
                body="""
                {
                  "release_dates": [
                    {
                      "release_id": 10,
                      "release_name": "Consumer Price Index",
                      "date": "2026-07-15"
                    },
                    {
                      "release_id": 999,
                      "release_name": "Unrelated Release",
                      "date": "2026-07-15"
                    }
                  ]
                }
                """,
            ),
        )
    )
    repository = ProviderCalendarRepository(
        provider=FREDCalendarProvider(config.providers[DataProviderId.FRED], http),
        cache=InMemoryCacheRepository(),
    )

    bundle = asyncio.run(repository.latest())

    assert bundle.events.status == ContractStatus.SUCCESS
    assert bundle.events.provider == DataProviderId.FRED.value
    assert bundle.events.data is not None
    assert len(bundle.events.data) == 1
    assert bundle.events.data[0].title == "Consumer Price Index"
    assert bundle.events.data[0].importance == "unrated"
    assert http.requests[0]["params"]["api_key"] == "test-fred-key"


def test_calendar_repository_fails_when_fred_unavailable(monkeypatch):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("FRED_API_KEY", "test-fred-key")
    http = FakeHttpClient(
        (
            HttpResponse(status_code=500, body="FRED unavailable"),
        )
    )
    repository = ProviderCalendarRepository(
        provider=FREDCalendarProvider(config.providers[DataProviderId.FRED], http),
        cache=InMemoryCacheRepository(),
    )

    bundle = asyncio.run(repository.latest())

    assert bundle.events.status == ContractStatus.FAILED
    assert bundle.events.data is None
    assert bundle.events.error == "FRED unavailable"


def test_repository_uses_cached_cot_when_provider_fails():
    config = load_platform_config("config/platform.json")
    cache = InMemoryCacheRepository()
    first_http = FakeHttpClient(
        (
            HttpResponse(
                status_code=200,
                body="""
                [
                  {
                    "report_date_as_yyyy_mm_dd": "2026-06-30",
                    "market_and_exchange_names": "GOLD - COMMODITY EXCHANGE INC.",
                    "m_money_positions_long_all": "180000",
                    "m_money_positions_short_all": "90000"
                  }
                ]
                """,
            ),
            HttpResponse(status_code=200, body=GLD_SAMPLE_JSON),
        )
    )
    repository = ProviderInstitutionalRepository(
        cot_provider=COTProvider(config.providers[DataProviderId.CFTC_COT], first_http),
        gld_provider=GLDProvider(config.providers[DataProviderId.SPDR_GLD], first_http),
        cache=cache,
    )
    asyncio.run(repository.latest())

    failing_http = FakeHttpClient(
        (
            HttpResponse(status_code=503, body="unavailable"),
            HttpResponse(status_code=503, body="unavailable"),
        )
    )
    repository = ProviderInstitutionalRepository(
        cot_provider=COTProvider(config.providers[DataProviderId.CFTC_COT], failing_http),
        gld_provider=GLDProvider(config.providers[DataProviderId.SPDR_GLD], failing_http),
        cache=cache,
    )

    bundle = asyncio.run(repository.latest())

    assert bundle.cot.status == ContractStatus.STALE_DATA
    assert bundle.cot.used_cache is True
    assert bundle.cot.confidence_penalty == 15
    assert bundle.cot.data is not None
    assert bundle.cot.data.net_position == 90000


def test_twelve_data_provider_uses_configured_auth_and_time_series_endpoint(monkeypatch):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    http = FakeHttpClient(
        (
            HttpResponse(
                status_code=200,
                body="""
                {
                  "values": [
                    {
                      "datetime": "2026-07-02T12:00:00+00:00",
                      "open": "2340.00",
                      "high": "2355.00",
                      "low": "2338.00",
                      "close": "2350.50",
                      "volume": "1200"
                    }
                  ]
                }
                """,
            ),
        )
    )
    provider = TwelveDataProvider(config.providers[DataProviderId.TWELVE_DATA], http)

    result = asyncio.run(provider.gold_ohlc(Timeframe.ONE_HOUR, output_size=1))

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data[0].symbol == MarketSymbol.XAU_USD
    assert result.data[0].close == Decimal("2350.50")
    assert http.requests[0]["params"]["apikey"] == "test-key"
    assert "/time_series" in http.requests[0]["url"]


def test_scheduler_publishes_typed_update_events():
    event_bus = InMemoryEventBus()
    scheduler = PollingScheduler(event_bus=event_bus)

    published = scheduler.publish_due_events(datetime.now(UTC) + timedelta(seconds=1))

    event_types = {event.event_type for event in event_bus.published_events}
    assert published
    assert EventType.COT_UPDATED in event_types
    assert EventType.ETF_UPDATED in event_types
    assert EventType.CALENDAR_UPDATED in event_types
    assert EventType.NEWS_UPDATED in event_types
    assert EventType.DXY_UPDATED in event_types
