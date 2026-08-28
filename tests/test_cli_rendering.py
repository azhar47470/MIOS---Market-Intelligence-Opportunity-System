import pytest
from app.main import _print_mode_output
from app.application.orchestrator import OrchestratorRunResult
from app.domain.intelligence import DecisionReport
from app.domain.enums import Recommendation
from app.domain.notification_models import ExpectedMove, SupportResistanceLevels
from app.domain.intelligence import MarketRegime
from app.domain.decisions import UnifiedDecision
from app.domain.intelligence import DirectionalBias
from app.domain.common import EvidenceRecord, ConfidenceScore, RiskRecord, EvidenceStrength
from app.domain.notification_models import InvalidationCondition
from datetime import datetime, UTC

def test_forex_rendering_does_not_crash(capsys):
    decision = DecisionReport(
        recommendation_id="123",
        recommendation=Recommendation.BUY,
        investment_score=80,
        opportunity_score=90,
        confidence=75,
        expected_move=ExpectedMove(direction="UP", min_usd=10, max_usd=20, summary="Up"),
        expected_holding_period="1w",
        market_regime=MarketRegime.BULL,
        supporting_evidence=(EvidenceRecord(evidence_id="1", category="test", description="desc", strength=EvidenceStrength.HIGH, confidence=80, source="src"),),
        contradicting_evidence=(),
        risk_summary=(RiskRecord(risk="test", severity=EvidenceStrength.LOW, probability=50),),
        invalidation_conditions=(InvalidationCondition(condition="price < 10"),),
        support_resistance=SupportResistanceLevels(support=(), resistance=()),
        explanation="Test",
        timestamp=datetime.now(UTC),
    )
    
    unified = UnifiedDecision(
        market_bias=DirectionalBias.BULLISH,
        confidence=80,
        reasoning="Test",
    )
    
    result = OrchestratorRunResult(
        decision=decision,
        unified_decision=unified,
        spot_price=2400.50
    )
    
    _print_mode_output(result, "forex")
    
    captured = capsys.readouterr()
    assert "Expected Move:" in captured.out
    assert "Entry: 2400.5" in captured.out

def test_etf_rendering_does_not_crash(capsys):
    decision = DecisionReport(
        recommendation_id="124",
        recommendation=Recommendation.BUY,
        investment_score=80,
        opportunity_score=90,
        confidence=75,
        expected_move=ExpectedMove(direction="UP", min_usd=10, max_usd=20, summary="Up"),
        expected_holding_period="1w",
        market_regime=MarketRegime.BULL,
        supporting_evidence=(EvidenceRecord(evidence_id="1", category="test", description="desc", strength=EvidenceStrength.HIGH, confidence=80, source="src"),),
        contradicting_evidence=(),
        risk_summary=(RiskRecord(risk="test", severity=EvidenceStrength.LOW, probability=50),),
        invalidation_conditions=(InvalidationCondition(condition="price < 10"),),
        support_resistance=SupportResistanceLevels(support=(), resistance=()),
        explanation="Test",
        timestamp=datetime.now(UTC),
    )
    
    unified = UnifiedDecision(
        market_bias=DirectionalBias.BULLISH,
        confidence=80,
        reasoning="Test",
    )
    
    result = OrchestratorRunResult(
        decision=decision,
        unified_decision=unified,
        spot_price=2400.50
    )
    
    _print_mode_output(result, "etf")
    
    captured = capsys.readouterr()
    assert "Expected Move: +$10" in captured.out
    assert "Vehicle    :" in captured.out
    assert "Flows      :" in captured.out
    assert "Allocation :" in captured.out
