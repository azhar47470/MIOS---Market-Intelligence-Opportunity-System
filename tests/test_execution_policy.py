import pytest
from unittest.mock import MagicMock
from app.application.execution_policy import ModeExecutionPolicy
from app.application.decision_config import DecisionThresholdConfig
from app.domain.intelligence import DirectionalBias

@pytest.fixture
def config():
    return DecisionThresholdConfig(
        physical_action_threshold=85,
        forex_action_threshold=60,
        forex_high_confidence_threshold=70,
        etf_action_threshold=70,
        physical_minimum_expected_move_usd=50,
        forex_minimum_expected_move_usd=10,
        etf_minimum_expected_move_usd=40
    )

@pytest.fixture
def policy(config):
    return ModeExecutionPolicy(config)

def build_mock_decision(confidence, high_risk=False, expected_move_usd=0, opp=100, inv=100):
    decision = MagicMock()
    decision.confidence = confidence
    decision.opportunity_score = opp
    decision.investment_score = inv
    if high_risk:
        risk = MagicMock()
        risk.severity.name = "HIGH"
        decision.risk_summary = [risk]
    else:
        decision.risk_summary = []
    
    move = MagicMock()
    move.min_usd = expected_move_usd
    decision.expected_move = move
    return decision

def build_mock_bundle(tech_bias, fundamental_bias=DirectionalBias.NEUTRAL, inst_bias=DirectionalBias.NEUTRAL):
    bundle = MagicMock()
    bundle.technical.bias = tech_bias
    bundle.fundamental.bias = fundamental_bias
    bundle.institutional.bias = inst_bias
    return bundle

def test_physical_policy(policy):
    bundle = build_mock_bundle(DirectionalBias.BULLISH)
    # 84% + expected move $100 -> WAIT
    res1 = policy.evaluate("physical", 84, DirectionalBias.BULLISH, build_mock_decision(84, expected_move_usd=100), bundle)
    assert not res1.actionable
    # 85% + expected move $50 -> eligible
    res2 = policy.evaluate("physical", 85, DirectionalBias.BULLISH, build_mock_decision(85, expected_move_usd=50), bundle)
    assert res2.actionable
    # 90% + expected move $49 -> WAIT
    res3 = policy.evaluate("physical", 90, DirectionalBias.BULLISH, build_mock_decision(90, expected_move_usd=49), bundle)
    assert not res3.actionable
    # 86% + expected move $10 -> WAIT
    res4 = policy.evaluate("physical", 86, DirectionalBias.BULLISH, build_mock_decision(86, expected_move_usd=10), bundle)
    assert not res4.actionable

def test_forex_policy(policy):
    bundle_aligned = build_mock_bundle(DirectionalBias.BULLISH)
    bundle_unaligned = build_mock_bundle(DirectionalBias.BEARISH)
    
    # 59% + $20 -> WAIT
    res1 = policy.evaluate("forex", 59, DirectionalBias.BULLISH, build_mock_decision(59, expected_move_usd=20), bundle_aligned)
    assert not res1.actionable
    
    # 60% + $10 -> eligible
    res2 = policy.evaluate("forex", 60, DirectionalBias.BULLISH, build_mock_decision(60, expected_move_usd=10), bundle_aligned)
    assert res2.actionable
    
    # 69% + $10 -> eligible
    res3 = policy.evaluate("forex", 69, DirectionalBias.BULLISH, build_mock_decision(69, expected_move_usd=10), bundle_aligned)
    assert res3.actionable
    
    # 70% + $5 -> WAIT
    res4 = policy.evaluate("forex", 70, DirectionalBias.BULLISH, build_mock_decision(70, expected_move_usd=5), bundle_aligned)
    assert not res4.actionable
    
    # 80% + $10 -> eligible
    res5 = policy.evaluate("forex", 80, DirectionalBias.BULLISH, build_mock_decision(80, expected_move_usd=10), bundle_aligned)
    assert res5.actionable

def test_etf_policy(policy):
    # 69% + $100 -> WAIT
    res1 = policy.evaluate("etf", 69, DirectionalBias.BULLISH, build_mock_decision(69, expected_move_usd=100), build_mock_bundle(DirectionalBias.BULLISH, DirectionalBias.BULLISH, DirectionalBias.BULLISH))
    assert not res1.actionable
    
    # 70% + $40 -> eligible
    res2 = policy.evaluate("etf", 70, DirectionalBias.BULLISH, build_mock_decision(70, expected_move_usd=40), build_mock_bundle(DirectionalBias.BULLISH, DirectionalBias.BULLISH, DirectionalBias.BULLISH))
    assert res2.actionable
    
    # 80% + $20 -> WAIT
    res3 = policy.evaluate("etf", 80, DirectionalBias.BULLISH, build_mock_decision(80, expected_move_usd=20), build_mock_bundle(DirectionalBias.BULLISH, DirectionalBias.BULLISH, DirectionalBias.BULLISH))
    assert not res3.actionable

def test_risk_safety(policy):
    bundle = build_mock_bundle(DirectionalBias.BULLISH)
    res1 = policy.evaluate("physical", 90, DirectionalBias.BULLISH, build_mock_decision(90, high_risk=True), bundle)
    assert not res1.actionable

def test_user_requested_cases(policy):
    bundle_aligned = build_mock_bundle(DirectionalBias.BULLISH, DirectionalBias.BULLISH, DirectionalBias.BULLISH)
    
    # CASE A - Forex can act
    res_a = policy.evaluate("forex", 69, DirectionalBias.BULLISH, build_mock_decision(69, opp=65, inv=65, expected_move_usd=35), bundle_aligned)
    assert res_a.actionable
    
    # CASE B - Physical blocks same setup
    res_b = policy.evaluate("physical", 86, DirectionalBias.BULLISH, build_mock_decision(86, opp=65, inv=65, expected_move_usd=35), bundle_aligned)
    assert not res_b.actionable
    assert "Expected move $35 is below Physical minimum $50" in res_b.reason or "score" in res_b.reason
    
    # CASE C - ETF uses middle thresholds
    res_c = policy.evaluate("etf", 72, DirectionalBias.BULLISH, build_mock_decision(72, opp=72, inv=66, expected_move_usd=45), bundle_aligned)
    assert res_c.actionable
    
    # CASE D - Universal risk
    res_d = policy.evaluate("forex", 90, DirectionalBias.BULLISH, build_mock_decision(90, high_risk=True, opp=100, inv=100, expected_move_usd=100), bundle_aligned)
    assert not res_d.actionable
    
    # CASE E - Low opportunity
    res_e = policy.evaluate("forex", 70, DirectionalBias.BULLISH, build_mock_decision(70, opp=55, inv=70, expected_move_usd=20), bundle_aligned)
    assert not res_e.actionable
    assert "opportunity score 55 is below required 60" in res_e.reason
    
    # CASE F - Low investment
    res_f = policy.evaluate("forex", 70, DirectionalBias.BULLISH, build_mock_decision(70, opp=70, inv=55, expected_move_usd=20), bundle_aligned)
    assert not res_f.actionable
    assert "investment score 55 is below required 60" in res_f.reason

