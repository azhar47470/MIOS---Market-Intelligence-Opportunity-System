from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.application.decision_config import DecisionEngineConfig, DecisionThresholdConfig
from app.application.engines.decision_engine import (
    DecisionEngine,
    InvestmentScoringEngine,
    OpportunityFilter,
)
from app.application.engines.fundamental_engine import FundamentalIntelligenceEngine
from app.application.engines.geopolitical_engine import GeopoliticalIntelligenceEngine
from app.application.engines.institutional_engine import InstitutionalIntelligenceEngine
from app.application.engines.news_engine import NewsIntelligenceEngine
from app.application.engines.regime_engine import MarketRegimeEngine
from app.application.engines.technical_engine import TechnicalIntelligenceEngine
from app.domain.enums import Recommendation
from app.domain.intelligence import AnalysisBundle, DecisionContext, MarketDataSnapshot
from app.domain.market_data import (
    CotPositioningSnapshot,
    DataProviderId,
    EtfFlowSnapshot,
    MacroSeriesObservation,
    MarketSymbol,
    NewsArticle,
    OhlcBar,
    Timeframe,
)


def make_bars(count: int = 35) -> tuple[OhlcBar, ...]:
    start = datetime(2026, 7, 2, 0, 0, tzinfo=UTC)
    bars = []
    for index in range(count):
        close = Decimal("2300") + Decimal(index * 3)
        bars.append(
            OhlcBar(
                symbol=MarketSymbol.XAU_USD,
                provider_symbol="XAU/USD",
                timeframe=Timeframe.ONE_HOUR,
                timestamp=start + timedelta(hours=index),
                open=close - Decimal("2"),
                high=close + Decimal("6"),
                low=close - Decimal("6"),
                close=close,
                volume=Decimal("1000"),
                provider=DataProviderId.TWELVE_DATA,
            )
        )
    return tuple(bars)


def test_decision_engine_can_generate_buy_when_evidence_alignment_is_strong():
    config = DecisionEngineConfig(
        thresholds=DecisionThresholdConfig(
            minimum_confidence_for_action=40,
            minimum_expected_move_usd=Decimal("1"),
        )
    )
    bars = make_bars()
    now = datetime.now(UTC)
    dxy = (
        MacroSeriesObservation(
            series_id="DTWEXBGS",
            date=now - timedelta(days=1),
            value=Decimal("105"),
            provider=DataProviderId.FRED,
        ),
        MacroSeriesObservation(
            series_id="DTWEXBGS",
            date=now,
            value=Decimal("104"),
            provider=DataProviderId.FRED,
        ),
    )
    cot = (
        CotPositioningSnapshot(
            report_date=now,
            market_name="GOLD - COMMODITY EXCHANGE INC.",
            managed_money_long=180000,
            managed_money_short=90000,
            managed_money_net=90000,
        ),
    )
    flow = EtfFlowSnapshot(
        date=now,
        fund="GLD",
        total_ounces=Decimal("25100000"),
        daily_ounce_change=Decimal("100000"),
    )
    articles = (
        NewsArticle(
            article_id="n1",
            title="Gold safe haven demand rises as war crisis meets dovish rate cut hopes",
            url="https://example.test/gold",
            source_name="Example",
            published_at=now,
            summary="Gold gains on safe haven flows.",
            provider=DataProviderId.NEWSAPI,
        ),
    )
    market_data = MarketDataSnapshot(
        bars=bars,
        dxy_observations=dxy,
        news_articles=articles,
        geopolitical_articles=articles,
        cot_positioning=cot,
        gld_flow=flow,
        collected_at=now,
    )
    technical = TechnicalIntelligenceEngine().analyze(bars)
    fundamental = FundamentalIntelligenceEngine().analyze(dxy, ())
    institutional = InstitutionalIntelligenceEngine().analyze(cot, flow)
    news = NewsIntelligenceEngine().analyze(articles)
    geopolitical = GeopoliticalIntelligenceEngine().analyze(articles)
    regime = MarketRegimeEngine(config.weights).analyze(technical, fundamental, news, geopolitical)
    analysis = AnalysisBundle(
        market_data=market_data,
        technical=technical,
        fundamental=fundamental,
        news=news,
        geopolitical=geopolitical,
        institutional=institutional,
        regime=regime,
    )
    opportunity = OpportunityFilter(config).assess(analysis)
    investment_score = InvestmentScoringEngine().score(analysis)
    report = DecisionEngine(config).decide(
        DecisionContext(
            market_data=market_data,
            technical=technical,
            fundamental=fundamental,
            news=news,
            geopolitical=geopolitical,
            institutional=institutional,
            regime=regime,
            opportunity=opportunity,
            investment_score=investment_score,
        )
    )

    assert report.recommendation in {Recommendation.BUY, Recommendation.STRONG_BUY}
    assert report.supporting_evidence
    assert report.invalidation_conditions
