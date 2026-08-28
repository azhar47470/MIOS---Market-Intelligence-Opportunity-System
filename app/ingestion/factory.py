from dataclasses import dataclass

from app.application.platform_config import PlatformConfig
from app.domain.market_data import DataProviderId
from app.infrastructure.http.urllib_http_client import UrlLibHttpClient
from app.infrastructure.ingestion.api_clients import (
    CftcCotClient,
    FredMacroClient,
    GdeltNewsClient,
    NewsApiClient,
    SpdrGldClient,
    TwelveDataMarketDataClient,
)


@dataclass(frozen=True)
class IngestionClients:
    twelve_data: TwelveDataMarketDataClient | None = None
    fred: FredMacroClient | None = None
    newsapi: NewsApiClient | None = None
    gdelt: GdeltNewsClient | None = None
    cftc_cot: CftcCotClient | None = None
    spdr_gld: SpdrGldClient | None = None


def build_ingestion_clients(config: PlatformConfig) -> IngestionClients:
    http_client = UrlLibHttpClient()

    def provider(provider_id: DataProviderId):
        provider_config = config.providers.get(provider_id)
        if provider_config is None or not provider_config.enabled:
            return None
        return provider_config

    twelve_data = provider(DataProviderId.TWELVE_DATA)
    fred = provider(DataProviderId.FRED)
    newsapi = provider(DataProviderId.NEWSAPI)
    gdelt = provider(DataProviderId.GDELT)
    cftc_cot = provider(DataProviderId.CFTC_COT)
    spdr_gld = provider(DataProviderId.SPDR_GLD)

    return IngestionClients(
        twelve_data=(
            TwelveDataMarketDataClient(twelve_data, http_client)
            if twelve_data is not None
            else None
        ),
        fred=FredMacroClient(fred, http_client) if fred is not None else None,
        newsapi=NewsApiClient(newsapi, http_client) if newsapi is not None else None,
        gdelt=GdeltNewsClient(gdelt, http_client) if gdelt is not None else None,
        cftc_cot=CftcCotClient(cftc_cot, http_client) if cftc_cot is not None else None,
        spdr_gld=SpdrGldClient(spdr_gld, http_client) if spdr_gld is not None else None,
    )
