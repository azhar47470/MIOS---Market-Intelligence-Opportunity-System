from dataclasses import dataclass

from app.application.cache import InMemoryCacheRepository
from app.application.market_data_collector import RepositoryBackedMarketDataCollector
from app.application.platform_config import PlatformConfig
from app.domain.market_data import DataProviderId
from app.infrastructure.http.urllib_http_client import UrlLibHttpClient
from app.infrastructure.providers.base import ProviderBase
from app.infrastructure.providers.cot_provider import COTProvider
from app.infrastructure.providers.dxy_provider import DXYProvider
from app.infrastructure.providers.fred_calendar_provider import FREDCalendarProvider
from app.infrastructure.providers.fred_macro_provider import FREDMacroProvider
from app.infrastructure.providers.gdelt_provider import GDELTProvider
from app.infrastructure.providers.gld_provider import GLDProvider
from app.infrastructure.providers.newsapi_provider import NewsAPIProvider
from app.infrastructure.providers.news_connector_provider import NewsConnectorProvider
from app.infrastructure.providers.rss_news_provider import RSSNewsProvider
from app.infrastructure.providers.twelve_data_provider import TwelveDataProvider
from app.infrastructure.repositories.provider_repositories import (
    ProviderCalendarRepository,
    ProviderInstitutionalRepository,
    ProviderMacroRepository,
    ProviderMarketRepository,
    ProviderNewsEventRepository,
)


@dataclass(frozen=True)
class ProviderRuntime:
    collector: RepositoryBackedMarketDataCollector
    cache: InMemoryCacheRepository


def build_provider_runtime(config: PlatformConfig) -> ProviderRuntime:
    http_client = UrlLibHttpClient()
    cache = InMemoryCacheRepository()

    twelve_config = config.providers[DataProviderId.TWELVE_DATA]
    fred_config = config.providers[DataProviderId.FRED]
    cot_config = config.providers[DataProviderId.CFTC_COT]
    gld_config = config.providers[DataProviderId.SPDR_GLD]
    gdelt_config = config.providers[DataProviderId.GDELT]
    newsapi_config = config.providers[DataProviderId.NEWSAPI]
    rss_news_config = config.providers[DataProviderId.RSS_NEWS]

    twelve_provider = TwelveDataProvider(twelve_config, http_client)
    fred_provider = ProviderBase(fred_config, http_client)
    fred_calendar_provider = FREDCalendarProvider(fred_config, http_client)
    fred_macro_provider = FREDMacroProvider(fred_config, http_client)
    dxy_provider = DXYProvider(fred_provider)
    cot_provider = COTProvider(cot_config, http_client)
    gld_provider = GLDProvider(gld_config, http_client)
    gdelt_provider = GDELTProvider(gdelt_config, http_client)
    newsapi_provider = NewsAPIProvider(newsapi_config, http_client)
    rss_news_provider = RSSNewsProvider(rss_news_config, http_client)

    institutional_repository = ProviderInstitutionalRepository(
        cot_provider=cot_provider,
        gld_provider=gld_provider,
        cache=cache,
        cot_ttl_seconds=cot_config.endpoints["cot_disaggregated"].cache_seconds,
        gld_ttl_seconds=gld_config.endpoints["gld_data"].cache_seconds,
    )
    calendar_repository = ProviderCalendarRepository(
        provider=fred_calendar_provider,
        cache=cache,
        ttl_seconds=fred_config.endpoints["releases_dates"].cache_seconds,
    )
    news_repository = ProviderNewsEventRepository(
        provider=gdelt_provider,
        cache=cache,
        ttl_seconds=gdelt_config.endpoints["doc_articles"].cache_seconds,
        connector_provider=NewsConnectorProvider(http_client),
        connector_ttl_seconds=900,
        fallback_provider=newsapi_provider,
        fallback_ttl_seconds=newsapi_config.endpoints["everything"].cache_seconds,
        rss_provider=rss_news_provider,
        rss_ttl_seconds=rss_news_config.endpoints["google_news"].cache_seconds,
    )
    market_repository = ProviderMarketRepository(
        twelve_data_provider=twelve_provider,
        dxy_provider=dxy_provider,
        cache=cache,
        dxy_ttl_seconds=300,
    )
    macro_repository = ProviderMacroRepository(
        provider=fred_macro_provider,
        cache=cache,
        series=config.macro_series,
    )
    return ProviderRuntime(
        collector=RepositoryBackedMarketDataCollector(
            market_repository=market_repository,
            institutional_repository=institutional_repository,
            calendar_repository=calendar_repository,
            news_repository=news_repository,
            macro_repository=macro_repository,
        ),
        cache=cache,
    )
