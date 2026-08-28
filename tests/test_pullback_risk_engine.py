import pytest
from datetime import datetime, UTC
from decimal import Decimal

from app.application.engines.pullback_risk_engine import PullbackRiskEngine
from app.domain.features import TechnicalSignalDirection, FairValueGap
from app.domain.market_data import OhlcBar, Timeframe
from app.domain.intelligence import MarketRegimeAnalysis, ConfidenceScore, MarketRegime, ContractStatus, EngineId, DirectionalBias

# Minimal mock for MarketRegimeAnalysis
def _mock_regime(regime=MarketRegime.BULL) -> MarketRegimeAnalysis:
    return MarketRegimeAnalysis(
        engine=EngineId.MARKET_REGIME,
        status=ContractStatus.SUCCESS,
        confidence=ConfidenceScore(value=80, reason="Test"),
        quality=100,
        score=80,
        regime=regime,
        bias=DirectionalBias.BULLISH,
        dynamic_weights={},
        evidence=(),
    )

def _mock_bars(closes, highs=None, lows=None) -> tuple[OhlcBar, ...]:
    highs = highs or [c * Decimal("1.01") for c in closes]
    lows = lows or [c * Decimal("0.99") for c in closes]
    
    bars = []
    base_time = datetime(2023, 1, 1, tzinfo=UTC)
    for i in range(len(closes)):
        bars.append(
            OhlcBar(
                symbol="XAU/USD",
                provider_symbol="XAU/USD",
                timeframe=Timeframe.ONE_DAY,
                timestamp=base_time,
                open=lows[i],
                high=highs[i],
                low=lows[i],
                close=closes[i],
                volume=Decimal("100"),
                provider="twelve_data"
            )
        )
    return tuple(bars)

def test_pullback_risk_engine_rsi_exhaustion():
    engine = PullbackRiskEngine()
    # Create an uptrend that is strongly overbought
    # RSI > 70
    # Make a steady steep uptrend
    closes = [Decimal(100 + i*5) for i in range(25)] 
    bars = _mock_bars(closes)
    
    report = engine.analyze(bars, _mock_regime())
    assert report.score > 0
    assert report.score <= 100
    assert any("RSI(14)" in driver for driver in report.drivers)
    
def test_pullback_risk_engine_momentum_weakening():
    engine = PullbackRiskEngine()
    # Create an uptrend that suddenly drops or flattens
    closes = [Decimal("100")] * 20 + [Decimal("150"), Decimal("140"), Decimal("130"), Decimal("125"), Decimal("120")]
    bars = _mock_bars(closes)
    
    report = engine.analyze(bars, _mock_regime())
    assert any("Momentum weakening" in driver or "Momentum flat" in driver for driver in report.drivers)

def test_pullback_risk_engine_strong_bullish_no_exhaustion():
    engine = PullbackRiskEngine()
    # Steady slow uptrend, no exhaustion
    closes = [Decimal(100 + i) for i in range(25)]
    bars = _mock_bars(closes)
    
    report = engine.analyze(bars, _mock_regime())
    assert report.score < 60
    
def test_pullback_risk_engine_neutral_conditions():
    engine = PullbackRiskEngine()
    # Flat market
    closes = [Decimal("100") for _ in range(25)]
    bars = _mock_bars(closes)
    
    report = engine.analyze(bars, _mock_regime(MarketRegime.RANGE))
    assert report.level in ["LOW", "MEDIUM"]
    assert report.score <= 50

def test_pullback_risk_engine_absent_drivers_low():
    engine = PullbackRiskEngine()
    # Normal trend
    closes = [Decimal(100 + i*0.5) for i in range(25)]
    bars = _mock_bars(closes)
    
    report = engine.analyze(bars, _mock_regime(MarketRegime.RANGE))
    # It shouldn't trigger extreme RSI, extreme extension, or momentum drop
    # Because momentum is positive, no sweep, no resistance proximity explicitly
    assert report.score < 60

def test_pullback_risk_engine_bounds():
    engine = PullbackRiskEngine()
    # Create extreme volatility, high extension, high RSI
    closes = [Decimal(100)] * 10 + [Decimal(100 + i*50) for i in range(15)]
    bars = _mock_bars(closes)
    
    report = engine.analyze(bars, _mock_regime(MarketRegime.HIGH_VOLATILITY))
    assert 0 <= report.score <= 100

def test_pullback_risk_engine_deterministic_repeatability():
    engine = PullbackRiskEngine()
    closes = [Decimal(100 + i*5) for i in range(25)]
    bars = _mock_bars(closes)
    
    report1 = engine.analyze(bars, _mock_regime())
    report2 = engine.analyze(bars, _mock_regime())
    
    assert report1.score == report2.score
    assert report1.level == report2.level
    assert report1.drivers == report2.drivers
