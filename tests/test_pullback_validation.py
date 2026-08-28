import pytest
from datetime import datetime, UTC, timedelta
from decimal import Decimal

from app.domain.market_data import OhlcBar, Timeframe
from app.application.engines.pullback_risk_engine import PullbackRiskReport

from scripts.validate_pullback_risk import PullbackValidator

class MockPullbackEngine:
    def __init__(self, scores):
        self.scores = scores
        self.idx = 0
        
    def analyze(self, bars, regime):
        score, level = self.scores[self.idx % len(self.scores)]
        self.idx += 1
        return PullbackRiskReport(
            score=score,
            level=level,
            directional_context="",
            drivers=[],
            warnings=[]
        )

def _mock_bars(closes) -> list[OhlcBar]:
    bars = []
    base_time = datetime(2023, 1, 1, tzinfo=UTC)
    for i, c in enumerate(closes):
        bars.append(
            OhlcBar(
                symbol="XAU/USD",
                provider_symbol="GC=F",
                timeframe=Timeframe.ONE_HOUR,
                timestamp=base_time + timedelta(hours=i),
                open=Decimal(str(c)),
                high=Decimal(str(c * 1.01)),
                low=Decimal(str(c * 0.99)),
                close=Decimal(str(c)),
                volume=Decimal("100"),
                provider="twelve_data"
            )
        )
    return bars

def test_validator_repeatability():
    # Two identical runs yield same result
    closes = [100 + i for i in range(100)]
    bars = _mock_bars(closes)
    
    engine = MockPullbackEngine([(20, "LOW")])
    validator = PullbackValidator(engine=engine)
    
    res1 = validator.validate(bars, lookback=10, max_forward_window=10, step_hours=5)
    
    engine.idx = 0 # reset mock
    res2 = validator.validate(bars, lookback=10, max_forward_window=10, step_hours=5)
    
    assert res1 == res2

def test_validator_no_lookahead_bias():
    closes = [100.0] * 50
    bars = _mock_bars(closes)
    
    class InspectingEngine:
        def __init__(self):
            self.max_time = None
        def analyze(self, window_bars, regime):
            self.max_time = max(b.timestamp for b in window_bars)
            return PullbackRiskReport(score=0, level="LOW", directional_context="", drivers=[], warnings=[])
            
    engine = InspectingEngine()
    validator = PullbackValidator(engine=engine)
    
    validator.validate(bars, lookback=10, max_forward_window=5, step_hours=10)
    
    # Engine should never see bars from the forward window
    # The last analyzed bar timestamp should be less than the end of the total bars array
    assert engine.max_time < bars[-1].timestamp
    
def test_validator_correct_forward_window_labeling():
    # We want to verify that the adverse excursion is calculated correctly.
    closes = [100.0] * 20
    # At index 10 (current_close = 100), the forward window (bars 11 to 15) has a low.
    # mock low is c * 0.99. If close is 90, low is 89.1.
    # Let's set bar 13 close to 90 so its low is 89.1
    # adverse excursion should be (100 - 89.1) / 100 = 0.109
    closes[13] = 90.0
    bars = _mock_bars(closes)
    
    engine = MockPullbackEngine([(80, "EXTREME")])
    validator = PullbackValidator(engine=engine)
    
    res = validator.validate(bars, lookback=10, max_forward_window=5, step_hours=10)
    
    # Only index 10 is evaluated (start_idx=10, step=10, end_idx=15)
    # The max adverse excursion for EXTREME should be around 0.109
    exc = res["EXTREME"]["max_adverse_excursion"]
    assert abs(exc - 0.109) < 0.001

def test_validator_score_bucket_assignment():
    closes = [100.0] * 30
    bars = _mock_bars(closes)
    
    # We alternate buckets
    engine = MockPullbackEngine([(20, "LOW"), (40, "MEDIUM"), (60, "HIGH"), (90, "EXTREME")])
    validator = PullbackValidator(engine=engine)
    
    # Evaluate at idx 10, 11, 12, 13
    res = validator.validate(bars, lookback=10, max_forward_window=10, step_hours=1)
    
    assert res["LOW"]["sample_count"] >= 1
    assert res["MEDIUM"]["sample_count"] >= 1
    assert res["HIGH"]["sample_count"] >= 1
    assert res["EXTREME"]["sample_count"] >= 1
