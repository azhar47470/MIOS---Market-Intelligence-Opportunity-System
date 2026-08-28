from datetime import UTC, datetime
from decimal import Decimal

from app.application.decision_config import DecisionEngineConfig
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
from app.backtesting.evaluation import directionally_correct
from app.backtesting.metrics import directional_hit_rate, wait_count
from app.backtesting.replay import HistoricalReplayer
from app.domain.enums import Recommendation
from app.domain.intelligence import AnalysisBundle, DecisionContext, MarketDataSnapshot
from app.domain.market_data import MarketQuote, OhlcBar
from app.domain.research import BacktestDecisionSample, BacktestResult, PaperValidationResult


class BacktestingEngine:
    def __init__(self, decision_config: DecisionEngineConfig) -> None:
        self._decision_config = decision_config
        self._technical_engine = TechnicalIntelligenceEngine()
        self._fundamental_engine = FundamentalIntelligenceEngine()
        self._institutional_engine = InstitutionalIntelligenceEngine()
        self._news_engine = NewsIntelligenceEngine()
        self._geopolitical_engine = GeopoliticalIntelligenceEngine()
        self._regime_engine = MarketRegimeEngine(decision_config.weights)
        self._opportunity_filter = OpportunityFilter(decision_config)
        self._scoring_engine = InvestmentScoringEngine()
        self._decision_engine = DecisionEngine(decision_config)
        self._replayer = HistoricalReplayer()

    def run(
        self, bars: tuple[OhlcBar, ...], lookback: int = 30, horizon: int = 5
    ) -> BacktestResult:
        started_at = datetime.now(UTC)
        samples: list[BacktestDecisionSample] = []
        windows = self._replayer.windows(bars=bars, lookback=lookback, horizon=horizon)
        if not windows:
            return BacktestResult(
                started_at=started_at,
                completed_at=datetime.now(UTC),
                samples=(),
                action_count=0,
                wait_count=0,
                directional_hit_rate=Decimal("0"),
            )

        for window in windows:
            decision = self._decide_window(window.lookback_bars)
            entry_price = window.lookback_bars[-1].close
            exit_price = window.future_bars[-1].close
            realized_move = exit_price - entry_price
            samples.append(
                BacktestDecisionSample(
                    decision=decision,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    realized_move_usd=realized_move,
                    was_directionally_correct=directionally_correct(
                        decision.recommendation, realized_move
                    ),
                )
            )

        samples_tuple = tuple(samples)
        return BacktestResult(
            started_at=started_at,
            completed_at=datetime.now(UTC),
            samples=samples_tuple,
            action_count=len(samples_tuple) - wait_count(samples_tuple),
            wait_count=wait_count(samples_tuple),
            directional_hit_rate=directional_hit_rate(samples_tuple),
        )

    def _decide_window(self, bars: tuple[OhlcBar, ...]):
        snapshot = MarketDataSnapshot(bars=bars, collected_at=bars[-1].timestamp)
        technical = self._technical_engine.analyze(bars)
        fundamental = self._fundamental_engine.analyze((), ())
        institutional = self._institutional_engine.analyze((), None)
        news = self._news_engine.analyze(())
        geopolitical = self._geopolitical_engine.analyze(())
        regime = self._regime_engine.analyze(technical, fundamental, news, geopolitical)
        analysis = AnalysisBundle(
            market_data=snapshot,
            technical=technical,
            fundamental=fundamental,
            news=news,
            geopolitical=geopolitical,
            institutional=institutional,
            regime=regime,
        )
        opportunity = self._opportunity_filter.assess(analysis)
        investment_score = self._scoring_engine.score(analysis)
        context = DecisionContext(
            market_data=snapshot,
            technical=technical,
            fundamental=fundamental,
            news=news,
            geopolitical=geopolitical,
            institutional=institutional,
            regime=regime,
            opportunity=opportunity,
            investment_score=investment_score,
        )
        return self._decision_engine.decide(context)


class PaperTradingValidator:
    def validate(
        self,
        decision_price: MarketQuote,
        current_price: MarketQuote,
        recommendation: Recommendation,
        recommendation_id: str,
    ) -> PaperValidationResult:
        move = current_price.price - decision_price.price
        return PaperValidationResult(
            recommendation_id=recommendation_id,
            recommendation=recommendation,
            reference_price=decision_price.price,
            current_price=current_price.price,
            unrealized_move_usd=move,
            status=_paper_status(recommendation, move),
            evaluated_at=datetime.now(UTC),
        )


def _paper_status(recommendation: Recommendation, move: Decimal) -> str:
    if recommendation in {Recommendation.BUY, Recommendation.STRONG_BUY} and move > 0:
        return "VALIDATING_POSITIVELY"
    if recommendation in {Recommendation.TAKE_PROFIT, Recommendation.STRONG_SELL} and move < 0:
        return "VALIDATING_POSITIVELY"
    if recommendation == Recommendation.WAIT:
        return "NO_ACTION_TO_VALIDATE"
    return "UNDER_REVIEW"
