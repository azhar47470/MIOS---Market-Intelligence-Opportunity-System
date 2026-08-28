import hashlib
from datetime import UTC, datetime

from app.application.source_repositories import (
    CalendarRepository,
    InstitutionalRepository,
    MacroRepository,
    MarketRepository,
    NewsEventRepository,
)
from app.domain.common import ContractStatus
from app.domain.intelligence import MarketDataSnapshot
from app.domain.market_data import (
    CotPositioningSnapshot,
    DataProviderId,
    EconomicCalendarEvent,
    EtfFlowSnapshot,
    MacroSeriesObservation,
    MarketQuote,
    MarketSymbol,
    NewsArticle,
)


class RepositoryBackedMarketDataCollector:
    def __init__(
        self,
        market_repository: MarketRepository,
        institutional_repository: InstitutionalRepository,
        calendar_repository: CalendarRepository,
        news_repository: NewsEventRepository,
        macro_repository: MacroRepository | None = None,
    ) -> None:
        self._market_repository = market_repository
        self._institutional_repository = institutional_repository
        self._calendar_repository = calendar_repository
        self._news_repository = news_repository
        self._macro_repository = macro_repository

    async def collect(self) -> tuple[MarketDataSnapshot, dict[str, ContractStatus]]:
        market = await self._market_repository.latest()
        institutional = await self._institutional_repository.latest()
        calendar = await self._calendar_repository.latest()
        # One combined query serves both the news and geopolitical engines. They used to be
        # two near-identical queries against the same repository, back to back - that was the
        # real cause of GDELT's repeated rate-limit rejections (confirmed across several live
        # runs: it kept rejecting the second call even 13-21+ seconds later, well past any
        # reasonable cooldown - the actual fix is not making a redundant second request). Each
        # engine already filters this shared article set for what's relevant to it, so nothing
        # downstream needs to change.
        articles = await self._news_repository.latest(
            'gold OR XAU/USD OR "gold price" OR "central bank" OR sanctions OR war '
            'OR conflict OR "geopolitical risk"'
        )
        news = articles
        geopolitical = articles
        macro = (
            await self._macro_repository.latest()
            if self._macro_repository is not None
            else None
        )
        statuses = {
            "repository_gold_price": market.gold_price.status,
            "repository_gold_bars": market.gold_bars.status,
            "repository_dxy": market.dxy.status,
            "repository_cot": institutional.cot.status,
            "repository_gld": institutional.gld.status,
            "repository_calendar": calendar.events.status,
            "repository_news": news.events.status,
            "repository_geopolitical": geopolitical.events.status,
        }
        if macro is not None:
            statuses["repository_macro"] = macro.observations.status
        provider_errors = {
            key: error
            for key, error in {
                "dxy": market.dxy.error,
                "cot": institutional.cot.error,
                "gld": institutional.gld.error,
                "calendar": calendar.events.error,
                "news": news.events.error,
                "geopolitical": geopolitical.events.error,
                "gold_price": market.gold_price.error,
                "gold_bars": market.gold_bars.error,
                "macro": macro.observations.error if macro is not None else None,
            }.items()
            if error
        }
        calendar_provider = _provider_id_from_source(
            calendar.events.provider,
            DataProviderId.FRED,
        )
        news_provider = _provider_id_from_source(
            news.events.provider,
            DataProviderId.GDELT,
        )
        return (
            MarketDataSnapshot(
                quote=_to_market_quote(market.gold_price.data),
                bars=market.gold_bars.data or (),
                dxy_observations=_to_dxy_observations(
                    market.dxy.data,
                    _provider_id_from_source(market.dxy.provider, DataProviderId.TWELVE_DATA),
                ),
                macro_observations=(macro.observations.data or ()) if macro is not None else (),
                economic_events=tuple(
                    EconomicCalendarEvent(
                        event_id=_stable_id(event.title, event.time.isoformat()),
                        country=event.country,
                        event=event.title,
                        impact=event.importance,
                        event_time=event.time,
                        actual=event.actual,
                        forecast=event.forecast,
                        previous=event.previous,
                        provider=calendar_provider,
                    )
                    for event in (calendar.events.data or ())
                ),
                news_articles=tuple(
                    _to_news_article(event, news_provider)
                    for event in (news.events.data or ())
                ),
                geopolitical_articles=tuple(
                    _to_news_article(
                        event,
                        _provider_id_from_source(
                            geopolitical.events.provider, DataProviderId.GDELT
                        ),
                    )
                    for event in (geopolitical.events.data or ())
                ),
                cot_positioning=(
                    (
                        CotPositioningSnapshot(
                            report_date=institutional.cot.data.report_date,
                            market_name="GOLD - COT",
                            managed_money_long=institutional.cot.data.long_positions,
                            managed_money_short=institutional.cot.data.short_positions,
                            managed_money_net=institutional.cot.data.net_position,
                        ),
                    )
                    if institutional.cot.data is not None
                    else ()
                ),
                gld_flow=(
                    EtfFlowSnapshot(
                        date=institutional.gld.data.date,
                        fund="GLD",
                        total_ounces=institutional.gld.data.ounces,
                        daily_ounce_change=institutional.gld.data.flow_delta,
                        total_tonnes=institutional.gld.data.total_tonnes,
                        total_nav_usd=institutional.gld.data.total_nav_usd,
                        shares_outstanding=institutional.gld.data.shares_outstanding,
                        field_dates=institutional.gld.data.field_dates,
                    )
                    if institutional.gld.data is not None
                    else None
                ),
                provider_errors=provider_errors,
                collected_at=datetime.now(UTC),
            ),
            statuses,
        )


def _to_market_quote(snapshot) -> MarketQuote | None:
    if snapshot is None:
        return None
    return MarketQuote(
        symbol=MarketSymbol.XAU_USD,
        provider_symbol="XAU/USD",
        price=snapshot.price,
        timestamp=snapshot.timestamp,
        provider=DataProviderId.TWELVE_DATA,
    )


def _to_dxy_observations(
    snapshot, provider: DataProviderId
) -> tuple[MacroSeriesObservation, ...]:
    if snapshot is None:
        return ()
    if snapshot.previous_price is not None and snapshot.previous_timestamp is not None:
        return (
            MacroSeriesObservation(
                series_id="DXY",
                date=snapshot.previous_timestamp,
                value=snapshot.previous_price,
                provider=provider,
            ),
            MacroSeriesObservation(
                series_id="DXY",
                date=snapshot.timestamp,
                value=snapshot.price,
                provider=provider,
            ),
        )
    return (
        MacroSeriesObservation(
            series_id="DXY",
            date=snapshot.timestamp,
            value=snapshot.price,
            provider=provider,
        ),
    )


def _provider_id_from_source(
    provider: str | None, default: DataProviderId
) -> DataProviderId:
    if provider is None:
        return default
    try:
        return DataProviderId(provider)
    except ValueError:
        return default


def _to_news_article(event, provider: DataProviderId) -> NewsArticle:
    return NewsArticle(
        article_id=_stable_id(event.url, event.date.isoformat()),
        title=event.headline,
        url=event.url,
        source_name=event.source or provider.value,
        published_at=event.date,
        summary=f"Tone: {event.tone}" if event.tone is not None else None,
        provider=provider,
    )


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
