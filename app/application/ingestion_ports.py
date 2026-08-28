from typing import Protocol

from app.domain.common import ProviderResult
from app.domain.market_data import (
    CotPositioningSnapshot,
    EtfFlowSnapshot,
    MacroSeriesObservation,
    MarketQuote,
    MarketSymbol,
    NewsArticle,
    OhlcBar,
    Timeframe,
)


class MarketDataProvider(Protocol):
    def get_quote(self, symbol: MarketSymbol) -> ProviderResult[MarketQuote]:
        """Fetch the latest quote for a market symbol."""

    def get_ohlc(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        output_size: int = 100,
    ) -> ProviderResult[tuple[OhlcBar, ...]]:
        """Fetch OHLC candles for a market symbol."""


class MacroDataProvider(Protocol):
    def get_series_observations(
        self,
        series_id: str,
        observation_start: str | None = None,
        observation_end: str | None = None,
    ) -> ProviderResult[tuple[MacroSeriesObservation, ...]]:
        """Fetch a macroeconomic time series."""


class NewsProvider(Protocol):
    def get_articles(self, query: str) -> ProviderResult[tuple[NewsArticle, ...]]:
        """Fetch articles matching a query."""


class InstitutionalDataProvider(Protocol):
    def get_gold_cot_positioning(self) -> ProviderResult[tuple[CotPositioningSnapshot, ...]]:
        """Fetch managed-money gold futures positioning."""

    def get_latest_gld_flow(self) -> ProviderResult[EtfFlowSnapshot]:
        """Fetch the latest GLD flow snapshot."""
