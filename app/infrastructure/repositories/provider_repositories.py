import asyncio

from app.application.cache import CacheRepository
from app.application.platform_config import MacroSeriesConfig
from app.application.source_repositories import (
    CalendarRepository,
    InstitutionalRepository,
    MacroRepository,
    MarketRepository,
    NewsEventRepository,
)
from app.domain.common import ContractStatus, ProviderResult
from app.domain.market_data import MacroSeriesObservation, OhlcBar, Timeframe
from app.domain.provider_snapshots import (
    COTSnapshot,
    DXYSnapshot,
    EconomicEventSnapshot,
    ETFSnapshot,
    GoldPriceSnapshot,
    NewsEventSnapshot,
)
from app.domain.source_data import (
    CalendarSourceBundle,
    InstitutionalSourceBundle,
    MacroSourceBundle,
    MarketSourceBundle,
    NewsSourceBundle,
    SourceReadResult,
)
from app.infrastructure.providers.cot_provider import COTProvider
from app.infrastructure.providers.dxy_provider import DXYProvider
from app.infrastructure.providers.fred_calendar_provider import FREDCalendarProvider
from app.infrastructure.providers.fred_macro_provider import FREDMacroProvider
from app.infrastructure.providers.gdelt_provider import GDELTProvider
from app.infrastructure.providers.gld_provider import GLDProvider
from app.infrastructure.providers.news_connector_provider import NewsConnectorProvider
from app.infrastructure.providers.newsapi_provider import GOLD_RELEVANT_QUERY, NewsAPIProvider
from app.infrastructure.providers.rss_news_provider import RSSNewsProvider
from app.infrastructure.providers.twelve_data_provider import TwelveDataProvider

MIN_NEWSAPI_CACHE_TTL_SECONDS = 1_800


class ProviderInstitutionalRepository(InstitutionalRepository):
    def __init__(
        self,
        cot_provider: COTProvider,
        gld_provider: GLDProvider,
        cache: CacheRepository,
        cot_ttl_seconds: int = 604_800,
        gld_ttl_seconds: int = 86_400,
    ) -> None:
        self._cot_provider = cot_provider
        self._gld_provider = gld_provider
        self._cache = cache
        self._cot_ttl_seconds = cot_ttl_seconds
        self._gld_ttl_seconds = gld_ttl_seconds

    async def latest(self) -> InstitutionalSourceBundle:
        cot = await _read_with_cache(
            key="institutional:cot:latest",
            provider_call=self._cot_provider.latest_gold_positions,
            model=COTSnapshot,
            cache=self._cache,
            ttl_seconds=self._cot_ttl_seconds,
        )
        gld = await _read_with_cache(
            key="institutional:gld:latest",
            provider_call=self._gld_provider.latest_flow,
            model=ETFSnapshot,
            cache=self._cache,
            ttl_seconds=self._gld_ttl_seconds,
        )
        return InstitutionalSourceBundle(cot=cot, gld=gld)


class ProviderCalendarRepository(CalendarRepository):
    """FRED release dates are the primary calendar source; the endpoint returns
    scheduled US release dates for the hardcoded gold-relevant FRED series."""

    def __init__(
        self,
        provider: FREDCalendarProvider,
        cache: CacheRepository,
        ttl_seconds: int = 300,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._ttl_seconds = ttl_seconds

    async def latest(self) -> CalendarSourceBundle:
        events = await _read_with_cache(
            key="calendar:fred:release_dates",
            provider_call=self._provider.upcoming_releases,
            model=tuple[EconomicEventSnapshot, ...],
            cache=self._cache,
            ttl_seconds=self._ttl_seconds,
        )
        return CalendarSourceBundle(events=events)


class ProviderNewsEventRepository(NewsEventRepository):
    def __init__(
        self,
        provider: GDELTProvider,
        cache: CacheRepository,
        ttl_seconds: int = 900,
        connector_provider: NewsConnectorProvider | None = None,
        connector_ttl_seconds: int = 900,
        fallback_provider: NewsAPIProvider | None = None,
        fallback_ttl_seconds: int = MIN_NEWSAPI_CACHE_TTL_SECONDS,
        rss_provider: RSSNewsProvider | None = None,
        rss_ttl_seconds: int = 900,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._ttl_seconds = ttl_seconds
        self._connector_provider = connector_provider
        self._connector_ttl_seconds = connector_ttl_seconds
        self._fallback_provider = fallback_provider
        self._fallback_ttl_seconds = max(
            fallback_ttl_seconds,
            MIN_NEWSAPI_CACHE_TTL_SECONDS,
        )
        self._rss_provider = rss_provider
        self._rss_ttl_seconds = rss_ttl_seconds

    async def latest(self, query: str) -> NewsSourceBundle:
        if self._connector_provider is not None:
            # Primary: v2 15-connector layer (official RSS, Reuters proxy, Finnhub
            # news, MarketAux, TheNewsAPI, WorldNewsAPI, Google News, RSS bridge).
            events = await _read_with_cache(
                key="news:connectors",
                provider_call=self._connector_provider.fetch_all,
                model=tuple[NewsEventSnapshot, ...],
                cache=self._cache,
                ttl_seconds=self._connector_ttl_seconds,
            )
            if events.status == ContractStatus.SUCCESS and events.data:
                return NewsSourceBundle(events=events)
        events = await _read_with_cache(
            key=f"gdelt:{query}",
            provider_call=lambda: self._provider.news_events(query),
            model=tuple[NewsEventSnapshot, ...],
            cache=self._cache,
            ttl_seconds=self._ttl_seconds,
        )
        if events.status == ContractStatus.SUCCESS:
            return NewsSourceBundle(events=events)
        if self._fallback_provider is not None:
            # NewsAPI's free tier permits 100 requests/day. A 1,800-second cache caps
            # this shared gold query at 48 calls/day; even separate news and
            # geopolitical query types would make at most 96 calls/day.
            events = await _read_with_cache(
                key="newsapi:gold-relevant",
                provider_call=lambda: self._fallback_provider.news_events(GOLD_RELEVANT_QUERY),
                model=tuple[NewsEventSnapshot, ...],
                cache=self._cache,
                ttl_seconds=self._fallback_ttl_seconds,
                reuse_fresh_cache=True,
            )
            if events.status == ContractStatus.SUCCESS:
                return NewsSourceBundle(events=events)
        if self._rss_provider is not None:
            # Keyless RSS layer (Google News feeds) keeps news flowing when the
            # paid/keyed providers are unavailable, so the news and geopolitical
            # engines never silently degrade to NO_DATA.
            events = await _read_with_cache(
                key="rss:news",
                provider_call=lambda: self._rss_provider.news_events(query),
                model=tuple[NewsEventSnapshot, ...],
                cache=self._cache,
                ttl_seconds=self._rss_ttl_seconds,
                reuse_fresh_cache=True,
            )
            return NewsSourceBundle(events=events)
        return NewsSourceBundle(events=events)


class ProviderMarketRepository(MarketRepository):
    def __init__(
        self,
        twelve_data_provider: TwelveDataProvider,
        dxy_provider: DXYProvider,
        cache: CacheRepository,
        dxy_ttl_seconds: int = 300,
    ) -> None:
        self._twelve_data_provider = twelve_data_provider
        self._dxy_provider = dxy_provider
        self._cache = cache
        self._dxy_ttl_seconds = dxy_ttl_seconds

    async def latest(self) -> MarketSourceBundle:
        gold_bars_h1 = await _read_with_cache(
            key="market:gold:bars:1h",
            provider_call=lambda: self._twelve_data_provider.gold_ohlc(Timeframe.ONE_HOUR),
            model=tuple[OhlcBar, ...],
            cache=self._cache,
            ttl_seconds=60,
        )
        gold_bars_h4 = await _read_with_cache(
            key="market:gold:bars:4h",
            provider_call=lambda: self._twelve_data_provider.gold_ohlc(Timeframe.FOUR_HOURS),
            model=tuple[OhlcBar, ...],
            cache=self._cache,
            ttl_seconds=300,
        )
        gold_bars_d1 = await _read_with_cache(
            key="market:gold:bars:1d",
            provider_call=lambda: self._twelve_data_provider.gold_ohlc(Timeframe.ONE_DAY, output_size=250),
            model=tuple[OhlcBar, ...],
            cache=self._cache,
            ttl_seconds=3600,
        )
        gold_bars = _combine_bar_results(gold_bars_h1, gold_bars_h4, gold_bars_d1)
        gold_price = _derive_gold_price_from_bars(gold_bars)
        dxy = await _read_with_cache(
            key="market:dxy:latest",
            provider_call=self._dxy_provider.latest_dxy,
            model=DXYSnapshot,
            cache=self._cache,
            ttl_seconds=self._dxy_ttl_seconds,
        )
        return MarketSourceBundle(gold_price=gold_price, gold_bars=gold_bars, dxy=dxy)


class ProviderMacroRepository(MacroRepository):
    """Cache-aware fan-out for configured FRED macro series."""

    def __init__(
        self,
        provider: FREDMacroProvider,
        cache: CacheRepository,
        series: dict[str, MacroSeriesConfig],
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._series = series

    async def latest(self) -> MacroSourceBundle:
        enabled_series = {
            series_id: config for series_id, config in self._series.items() if config.enabled
        }
        if not enabled_series:
            return MacroSourceBundle(
                observations=SourceReadResult(
                    status=ContractStatus.NO_DATA,
                    error="No macro series enabled.",
                )
            )
        results = await asyncio.gather(
            *(
                _read_with_cache(
                    key=f"macro:fred:{series_id}",
                    provider_call=(
                        lambda series_id=series_id: self._provider.series_observations(series_id)
                    ),
                    model=tuple[MacroSeriesObservation, ...],
                    cache=self._cache,
                    ttl_seconds=config.cache_seconds,
                )
                for series_id, config in enabled_series.items()
            )
        )
        observations = tuple(item for result in results for item in (result.data or ()))
        errors = tuple(result.error for result in results if result.error)
        if all(result.status == ContractStatus.SUCCESS for result in results):
            status = ContractStatus.SUCCESS
        elif observations:
            status = ContractStatus.PARTIAL_SUCCESS
        else:
            status = ContractStatus.NO_DATA
        return MacroSourceBundle(
            observations=SourceReadResult(
                status=status,
                data=observations,
                provider="fred",
                used_cache=any(result.used_cache for result in results),
                confidence_penalty=max(result.confidence_penalty for result in results),
                error="; ".join(errors)[:1000] if errors else None,
            )
        )


async def _read_with_cache[T](
    key: str,
    provider_call,
    model: type[T],
    cache: CacheRepository,
    ttl_seconds: int,
    reuse_fresh_cache: bool = False,
) -> SourceReadResult[T]:
    if reuse_fresh_cache:
        cached = cache.get(key)
        if cached is not None:
            cached_payload, cached_provider = _unwrap_cache_payload(cached.payload)
            return SourceReadResult(
                status=ContractStatus.SUCCESS,
                data=_validate_model(model, cached_payload),
                provider=cached_provider,
                used_cache=True,
            )

    result: ProviderResult[T] = await provider_call()
    if result.status == ContractStatus.SUCCESS and result.data is not None:
        payload = _cache_payload(result.data, result.provider)
        cache.set(key, payload, ttl_seconds)
        return SourceReadResult(status=result.status, data=result.data, provider=result.provider)

    cached = cache.get(key)
    if cached is not None:
        cached_payload, cached_provider = _unwrap_cache_payload(cached.payload)
        data = _validate_model(model, cached_payload)
        return SourceReadResult(
            status=ContractStatus.STALE_DATA,
            data=data,
            provider=cached_provider or result.provider,
            used_cache=True,
            confidence_penalty=15,
            error=result.error,
        )
    return SourceReadResult(status=result.status, error=result.error)


def _dump_model(data):
    if isinstance(data, tuple):
        return {"items": [item.model_dump(mode="json") for item in data]}
    return data.model_dump(mode="json")


def _cache_payload(data, provider: str) -> dict:
    return {"provider": provider, "data": _dump_model(data)}


def _unwrap_cache_payload(payload: dict) -> tuple[dict, str | None]:
    if "data" in payload and "provider" in payload:
        return payload["data"], payload.get("provider")
    return payload, None


def _combine_bar_results(
    *results: SourceReadResult[tuple[OhlcBar, ...]]
) -> SourceReadResult[tuple[OhlcBar, ...]]:
    combined = tuple()
    for res in results:
        if res.data:
            combined += tuple(res.data)
        
    all_success = all(res.status == ContractStatus.SUCCESS for res in results)
    
    if all_success:
        status = ContractStatus.SUCCESS
    elif combined:
        status = ContractStatus.PARTIAL_SUCCESS
    else:
        status = results[0].status

    provider = next((res.provider for res in results if res.provider), None)
    used_cache = any(res.used_cache for res in results)
    error = next((res.error for res in results if res.error), None)
    
    return SourceReadResult(
        status=status,
        data=combined,
        provider=provider,
        used_cache=used_cache,
        error=error,
        
    )

def _derive_gold_price_from_bars(
    bars: SourceReadResult[tuple[OhlcBar, ...]],
) -> SourceReadResult[GoldPriceSnapshot]:
    if bars.data:
        latest = max(bars.data, key=lambda bar: bar.timestamp)
        return SourceReadResult(
            status=bars.status,
            data=GoldPriceSnapshot(price=latest.close, timestamp=latest.timestamp),
            provider=latest.provider.value,
            used_cache=bars.used_cache,
            confidence_penalty=bars.confidence_penalty,
            error=bars.error,
        )
    return SourceReadResult(
        status=bars.status,
        error=bars.error or "No gold OHLC bars available to derive quote.",
    )


def _validate_model(model, payload):
    if getattr(model, "__origin__", None) is tuple:
        item_model = model.__args__[0]
        return tuple(item_model.model_validate(item) for item in payload.get("items", ()))
    return model.model_validate(payload)
