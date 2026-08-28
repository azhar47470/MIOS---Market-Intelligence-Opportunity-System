from datetime import UTC, datetime

from app.application.decision_config import DecisionWeightsConfig
from app.domain.common import (
    ConfidenceScore,
    ContractStatus,
    EvidenceRecord,
    EvidenceStrength,
    RiskRecord,
)
from app.domain.intelligence import (
    DirectionalBias,
    EngineId,
    FundamentalAnalysis,
    GeopoliticalAnalysis,
    MarketRegime,
    MarketRegimeAnalysis,
    NewsAnalysis,
    TechnicalAnalysis,
)


class MarketRegimeEngine:
    def __init__(self, weights_config: DecisionWeightsConfig) -> None:
        self._weights_config = weights_config

    def analyze(
        self,
        technical: TechnicalAnalysis,
        fundamental: FundamentalAnalysis,
        news: NewsAnalysis,
        geopolitical: GeopoliticalAnalysis,
    ) -> MarketRegimeAnalysis:
        started_at = datetime.now(UTC)
        regime = self._classify(technical, fundamental, news, geopolitical)
        score = self._score_for_regime(regime)
        confidence = min(
            90,
            round(
                (
                    technical.confidence.value
                    + fundamental.confidence.value
                    + news.confidence.value
                    + geopolitical.confidence.value
                )
                / 4
            ),
        )
        return MarketRegimeAnalysis(
            engine=EngineId.MARKET_REGIME,
            status=ContractStatus.SUCCESS,
            confidence=ConfidenceScore(
                value=confidence, reason=f"Regime classified as {regime.value}."
            ),
            quality=confidence,
            score=score,
            bias=_bias_for_regime(regime),
            evidence=(
                EvidenceRecord(
                    evidence_id="REGIME-001",
                    category="Regime",
                    description=f"Market regime classified as {regime.value}.",
                    strength=EvidenceStrength.HIGH if confidence >= 70 else EvidenceStrength.MEDIUM,
                    confidence=confidence,
                    source="Market Regime Engine",
                ),
            ),
            risks=(
                RiskRecord(
                    risk="Regime can change quickly around macro releases and geopolitical events.",
                    severity=EvidenceStrength.MEDIUM,
                    probability=50,
                ),
            ),
            execution_ms=_elapsed_ms(started_at),
            regime=regime,
            dynamic_weights=self._weights_config.regime_overrides.get(
                regime, self._weights_config.base_weights
            ),
        )

    def _classify(
        self,
        technical: TechnicalAnalysis,
        fundamental: FundamentalAnalysis,
        news: NewsAnalysis,
        geopolitical: GeopoliticalAnalysis,
    ) -> MarketRegime:
        if fundamental.high_impact_event_count > 0:
            return MarketRegime.EVENT_DRIVEN
        if geopolitical.risk_score >= 70:
            return MarketRegime.RISK_OFF
        if technical.volatility_score >= 70:
            return MarketRegime.HIGH_VOLATILITY
        if technical.volatility_score <= 20 and technical.status == ContractStatus.SUCCESS:
            return MarketRegime.LOW_VOLATILITY
        if (
            technical.bias == DirectionalBias.BULLISH
            and fundamental.bias != DirectionalBias.BEARISH
        ):
            return MarketRegime.BULL
        if (
            technical.bias == DirectionalBias.BEARISH
            and fundamental.bias != DirectionalBias.BULLISH
        ):
            return MarketRegime.BEAR
        return MarketRegime.RANGE

    def _score_for_regime(self, regime: MarketRegime) -> int:
        scores = {
            MarketRegime.BULL: 70,
            MarketRegime.BEAR: 35,
            MarketRegime.RANGE: 50,
            MarketRegime.RISK_ON: 40,
            MarketRegime.RISK_OFF: 65,
            MarketRegime.HIGH_VOLATILITY: 45,
            MarketRegime.LOW_VOLATILITY: 50,
            MarketRegime.EVENT_DRIVEN: 45,
            MarketRegime.UNKNOWN: 50,
        }
        return scores[regime]


def _bias_for_regime(regime: MarketRegime) -> DirectionalBias:
    if regime in {MarketRegime.BULL, MarketRegime.RISK_OFF}:
        return DirectionalBias.BULLISH
    if regime in {MarketRegime.BEAR, MarketRegime.RISK_ON}:
        return DirectionalBias.BEARISH
    return DirectionalBias.NEUTRAL


def _elapsed_ms(started_at: datetime) -> int:
    return int((datetime.now(UTC) - started_at).total_seconds() * 1000)
