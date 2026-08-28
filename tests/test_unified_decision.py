from datetime import UTC, datetime
from decimal import Decimal

from app.application.adapters.etf import GoldETFAdapter
from app.application.adapters.forex import ForexAdapter
from app.application.adapters.physical import PhysicalGoldAdapter
from app.application.adapters.unified import UnifiedDecisionBuilder
from app.domain.ai import (
    AgentRole,
    AnalystReport,
    CommitteeVoteSnapshot,
    InvestmentCommitteeReport,
    ResearchDeskReport,
)
from app.domain.decisions import UnifiedDecision
from app.domain.enums import Recommendation
from app.domain.intelligence import (
    AnalysisBundle,
    DecisionReport,
    DirectionalBias,
    EngineId,
    FundamentalAnalysis,
    GeopoliticalAnalysis,
    InstitutionalAnalysis,
    MarketDataSnapshot,
    MarketNarrative,
    MarketRegime,
    MarketRegimeAnalysis,
    NewsAnalysis,
    TechnicalAnalysis,
)
from app.domain.common import ConfidenceScore, ContractStatus
from app.domain.notification_models import (
    ExpectedMove,
    InvalidationCondition,
    NotificationPriority,
    SupportResistanceLevels,
)
from app.domain.common import EvidenceRecord, EvidenceStrength, RiskRecord

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _unified(
    bias: DirectionalBias = DirectionalBias.NEUTRAL,
    confidence: int = 50,
    narratives: tuple[str, ...] = (),
) -> UnifiedDecision:
    return UnifiedDecision(
        market_bias=bias,
        confidence=confidence,
        risk="low" if confidence <= 55 else "medium",
        narratives=narratives,
        committee_votes=(
            CommitteeVoteSnapshot(
                member_name="Macro Strategist", direction="BUY", confidence=0.7, weight=0.3, reasoning="r"
            ),
        ),
        engine_signals={"technical": "bullish", "news": "neutral"},
        reasoning="Gold outlook is neutral at 50% confidence (committee consensus: moderate).",
        timestamp=_NOW,
    )


def _decision_report(recommendation: Recommendation, confidence: int) -> DecisionReport:
    return DecisionReport(
        recommendation_id="rec-1",
        recommendation=recommendation,
        investment_score=60,
        opportunity_score=55,
        confidence=confidence,
        expected_move=ExpectedMove(direction="SIDEWAYS", summary="Range"),
        expected_holding_period="1-2 weeks",
        market_regime=MarketRegime.RANGE,
        supporting_evidence=(
            EvidenceRecord(
                evidence_id="e1",
                category="Technical",
                description="Support held",
                strength=EvidenceStrength.MEDIUM,
                confidence=60,
                source="technical_engine",
            ),
        ),
        contradicting_evidence=(),
        risk_summary=(
            RiskRecord(
                risk="Dollar strength",
                severity=EvidenceStrength.HIGH,
                probability=60,
            ),
        ),
        invalidation_conditions=(
            InvalidationCondition(
                condition="Break below support",
                severity=NotificationPriority.NORMAL,
            ),
        ),
        support_resistance=SupportResistanceLevels(),
        explanation="Range-bound evidence.",
        timestamp=_NOW,
    )


def _bundle(narratives: tuple[MarketNarrative, ...]) -> AnalysisBundle:
    def with_bias(model, bias: DirectionalBias):
        return model.model_copy(update={"bias": bias})

    return AnalysisBundle(
        market_data=MarketDataSnapshot(collected_at=_NOW, narratives=narratives),
        technical=with_bias(_TECHNICAL, DirectionalBias.BULLISH),
        fundamental=with_bias(_FUNDAMENTAL, DirectionalBias.NEUTRAL),
        news=with_bias(_NEWS, DirectionalBias.NEUTRAL),
        geopolitical=with_bias(_GEOPOLITICAL, DirectionalBias.NEUTRAL),
        institutional=with_bias(_INSTITUTIONAL, DirectionalBias.NEUTRAL),
        regime=with_bias(_REGIME, DirectionalBias.MIXED),
    )


_ANALYSIS_BASE = {
    "status": ContractStatus.SUCCESS,
    "confidence": ConfidenceScore(value=50, reason="test"),
    "quality": 60,
    "score": 55,
    "bias": DirectionalBias.NEUTRAL,
}

_TECHNICAL = TechnicalAnalysis(
    **_ANALYSIS_BASE,
    engine=EngineId.TECHNICAL,
    trend_strength=60,
    momentum_score=60,
    volatility_score=40,
    support_resistance=SupportResistanceLevels(),
)
_FUNDAMENTAL = FundamentalAnalysis(
    **_ANALYSIS_BASE,
    engine=EngineId.FUNDAMENTAL,
    macro_narrative="mixed",
    dollar_bias=DirectionalBias.NEUTRAL,
    high_impact_event_count=0,
)
_NEWS = NewsAnalysis(
    **_ANALYSIS_BASE,
    engine=EngineId.NEWS,
    analyzed_articles=0,
    high_severity_events=0,
)
_GEOPOLITICAL = GeopoliticalAnalysis(
    **_ANALYSIS_BASE,
    engine=EngineId.GEOPOLITICAL,
    risk_score=30,
    conflict_status="calm",
    expected_market_impact=DirectionalBias.NEUTRAL,
)
_INSTITUTIONAL = InstitutionalAnalysis(
    **_ANALYSIS_BASE,
    engine=EngineId.INSTITUTIONAL,
    positioning_summary="neutral",
    etf_flow_score=50,
    cot_score=50,
)
_REGIME = MarketRegimeAnalysis(
    **_ANALYSIS_BASE,
    engine=EngineId.MARKET_REGIME,
    regime=MarketRegime.RANGE,
    dynamic_weights={},
)


def test_builder_maps_recommendation_to_bias_and_context():
    research = ResearchDeskReport(
        analyst_reports=(
            AnalystReport(
                report_id="det-1",
                role=AgentRole.TECHNICAL_ANALYST,
                context_id="c",
                provider="deterministic_fallback",
                summary="Desk report.",
                confidence=70,
                recommendation=Recommendation.BUY,
            ),
        ),
        committee_report=InvestmentCommitteeReport(
            report_id="r",
            context_id="c",
            provider="adversarial_committee",
            final_recommendation=Recommendation.BUY,
            confidence=70,
            summary="Moderate consensus: buy 55%, sell 20%, wait 25% across 4 members.",
            confidence_adjustment=4,
            why_not_buy="counter",
            why_not_sell="counter",
            committee_votes=(
                CommitteeVoteSnapshot(
                    member_name="Macro Strategist",
                    direction="BUY",
                    confidence=0.7,
                    weight=0.3,
                    reasoning="r",
                ),
            ),
        ),
    )
    narratives = (MarketNarrative(narrative_id="n1", name="Rate Cut Cycle", strength=0.6),)

    unified = UnifiedDecisionBuilder().build(
        decision=_decision_report(Recommendation.STRONG_BUY, 80),
        bundle=_bundle(narratives),
        research=research,
    )

    assert unified.market_bias is DirectionalBias.BULLISH
    assert unified.confidence == 80
    assert unified.risk == "high"
    assert unified.narratives == ("Rate Cut Cycle",)
    assert len(unified.committee_votes) == 1
    assert unified.engine_signals["technical"] == "bullish"
    assert "bullish" in unified.reasoning
    assert "Rate Cut Cycle" in unified.reasoning


def test_builder_without_research_produces_valid_outlook():
    unified = UnifiedDecisionBuilder().build(
        decision=_decision_report(Recommendation.TAKE_PROFIT, 40),
        bundle=_bundle(()),
        research=None,
    )

    assert unified.market_bias is DirectionalBias.BEARISH
    assert unified.risk == "low"
    assert unified.committee_votes == ()
    assert "bearish" in unified.reasoning


def test_forex_adapter_computes_entry_targets_from_spot():
    decision = ForexAdapter().adapt(_unified(DirectionalBias.BULLISH, 80), spot=4050.25)

    assert decision.signal == "LONG"
    assert decision.entry == 4050.25
    assert decision.take_profit == round(4050.25 * 1.04, 2)
    assert decision.stop_loss == round(4050.25 * 0.98, 2)
    assert decision.risk == "medium"


def test_forex_adapter_shorts_on_bearish_bias():
    decision = ForexAdapter().adapt(_unified(DirectionalBias.BEARISH, 70), spot=4000)

    assert decision.signal == "SHORT"
    assert decision.take_profit < decision.entry
    assert decision.stop_loss > decision.entry


def test_forex_adapter_waits_without_spot():
    decision = ForexAdapter().adapt(_unified(DirectionalBias.NEUTRAL), spot=None)

    assert decision.signal == "WAIT"
    assert decision.entry is None
    assert decision.take_profit is None


def test_physical_adapter_recommendation_scales_with_confidence():
    strong = PhysicalGoldAdapter().adapt(_unified(DirectionalBias.BULLISH, 90))
    weak = PhysicalGoldAdapter().adapt(_unified(DirectionalBias.BULLISH, 60))
    hold = PhysicalGoldAdapter().adapt(_unified(DirectionalBias.NEUTRAL, 60))

    assert strong.recommendation == "STRONG BUY"
    assert weak.recommendation == "BUY"
    assert hold.recommendation == "HOLD"
    assert strong.action == "Accumulate aggressively"
    assert strong.reasons
    assert "constructive" in strong.thesis


def test_etf_adapter_uses_narrative_flow_context():
    decision = GoldETFAdapter().adapt(
        _unified(DirectionalBias.BULLISH, 75, narratives=("Gold ETF Flows",))
    )

    assert decision.recommendation == "STRONG BUY"
    assert "supportive" in decision.flow_context
    assert "GLD" in decision.vehicle_guidance
    assert decision.confidence == 75

def test_physical_adapter_obeys_is_actionable_flag():
    unified = _unified(DirectionalBias.BULLISH, 90)
    
    # Normally 90% BULLISH means STRONG BUY and aggressive allocation
    actionable = PhysicalGoldAdapter().adapt(unified, is_actionable=True)
    assert actionable.action == "Accumulate aggressively"
    assert "Increase allocation significantly" in actionable.allocation_guidance
    
    # If policy overrides to WAIT
    blocked = PhysicalGoldAdapter().adapt(unified, is_actionable=False)
    assert blocked.action == "WAIT"
    assert "Maintain current allocation; wait for stronger confirmation" in blocked.allocation_guidance
    
    # But it must preserve the underlying thesis (e.g. constructive outlook)
    assert "constructive" in blocked.thesis


def test_forex_adapter_actionable_long_keeps_entry_targets():
    decision = ForexAdapter().adapt(
        _unified(DirectionalBias.BULLISH, 80), spot=4050.25, is_actionable=True
    )

    assert decision.signal == "LONG"
    assert decision.entry == 4050.25
    assert decision.take_profit == round(4050.25 * 1.04, 2)
    assert decision.stop_loss == round(4050.25 * 0.98, 2)


def test_forex_adapter_actionable_short_keeps_entry_targets():
    decision = ForexAdapter().adapt(
        _unified(DirectionalBias.BEARISH, 70), spot=4000.0, is_actionable=True
    )

    assert decision.signal == "SHORT"
    assert decision.entry == 4000.0
    assert decision.take_profit == round(4000.0 * 0.96, 2)
    assert decision.stop_loss == round(4000.0 * 1.02, 2)


def test_forex_adapter_wait_carries_no_trade_parameters_when_not_actionable():
    for bias in (DirectionalBias.BULLISH, DirectionalBias.BEARISH):
        decision = ForexAdapter().adapt(_unified(bias, 80), spot=4050.25, is_actionable=False)

        assert decision.signal == "WAIT"
        assert decision.entry is None
        assert decision.take_profit is None
        assert decision.stop_loss is None
        assert decision.confidence == 80

def test_etf_adapter_obeys_is_actionable_flag():
    from app.application.adapters.etf import GoldETFAdapter
    unified = _unified(DirectionalBias.BULLISH, 90)
    
    # Normally 90% BULLISH means STRONG BUY and aggressive allocation
    actionable = GoldETFAdapter().adapt(unified, is_actionable=True)
    assert actionable.action == "Build / add to a core gold ETF position"
    assert "Increase gold ETF sleeve significantly" in actionable.allocation_guidance
    
    # If policy overrides to WAIT
    blocked = GoldETFAdapter().adapt(unified, is_actionable=False)
    assert blocked.action == "WAIT"
    assert "Maintain current ETF allocation; wait for stronger confirmation" in blocked.allocation_guidance
    
    # But it must preserve the underlying thesis (e.g. constructive outlook)
    assert "constructive" in blocked.thesis
