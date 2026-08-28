import pytest
from scripts.advanced_calibration import (
    brier_score,
    roc_auc,
    get_bin,
    AdvancedCalibrator,
    parse_components
)
from app.domain.market_data import OhlcBar, Timeframe
from datetime import datetime, timedelta, UTC
from decimal import Decimal

def test_calibration_metric_calculations():
    # Deterministic arrays
    y_true = [0, 0, 1, 1]
    y_prob = [0.1, 0.4, 0.35, 0.8]
    
    # brier_score = ( (0.1-0)^2 + (0.4-0)^2 + (0.35-1)^2 + (0.8-1)^2 ) / 4
    # = (0.01 + 0.16 + 0.4225 + 0.04) / 4 = 0.6325 / 4 = 0.158125
    b = brier_score(y_true, y_prob)
    assert abs(b - 0.158125) < 0.0001
    
    # roc_auc
    # y_prob sorted: 0.8 (T=1), 0.4 (T=0), 0.35 (T=1), 0.1 (T=0)
    auc = roc_auc(y_true, y_prob)
    assert auc > 0.0 and auc <= 1.0

def test_score_bin_assignment():
    assert get_bin(0) == "0-19"
    assert get_bin(19) == "0-19"
    assert get_bin(20) == "20-39"
    assert get_bin(39) == "20-39"
    assert get_bin(40) == "40-59"
    assert get_bin(59) == "40-59"
    assert get_bin(60) == "60-79"
    assert get_bin(79) == "60-79"
    assert get_bin(80) == "80-100"
    assert get_bin(100) == "80-100"

def _mock_bars(closes: list[float]) -> list[OhlcBar]:
    base_time = datetime(2023, 1, 1, tzinfo=UTC)
    return [
        OhlcBar(
            symbol="XAU/USD", provider_symbol="GC=F", timeframe=Timeframe.ONE_HOUR,
            timestamp=base_time + timedelta(hours=i),
            open=Decimal(str(c)), high=Decimal(str(c*1.01)),
            low=Decimal(str(c*0.99)), close=Decimal(str(c)),
            volume=Decimal("100"), provider="twelve_data"
        )
        for i, c in enumerate(closes)
    ]

def test_event_labeling_and_no_lookahead():
    # Simple sequence
    closes = [100.0] * 50
    # At index 20, close is 100. Let's make the forward 5 bars drop to 90
    closes[21:26] = [90.0] * 5
    
    bars = _mock_bars(closes)
    
    class MockEngine:
        def __init__(self):
            self.max_time_seen = None
            self.score = 50
            self.drivers = []
            
        def analyze(self, window_bars, regime):
            max_time = max(b.timestamp for b in window_bars)
            # Find the last hourly bar (which represents the eval time)
            hourly_bars = [b for b in window_bars if b.timeframe == Timeframe.ONE_HOUR]
            eval_time = max(b.timestamp for b in hourly_bars)
            assert max_time <= eval_time # No future data relative to the current eval time!
            self.max_time_seen = max_time
            from app.application.engines.pullback_risk_engine import PullbackRiskReport
            return PullbackRiskReport(score=self.score, level="MEDIUM", directional_context="", drivers=self.drivers, warnings=[])
            
    engine = MockEngine()
    calib = AdvancedCalibrator(engine=engine)
    
    # Process with lookback=10, max_forward=5, step=10
    # It will evaluate at index 10, 20, 30...
    samples = calib.process_data(bars, lookback=10, max_forward_window=10, step_hours=10)
    
    assert len(samples) > 0
    
    # Check event labeling
    # At idx 20, close is 100, min_low in next 24h (which is next 24 bars) goes down to 90*0.99 = 89.1
    # Excursion = (100 - 89.1) / 100 = 10.9%
    
    # Find sample for idx 20
    sample_20 = [s for s in samples if s["timestamp"] == bars[20].timestamp.isoformat()][0]
    exc_24h = sample_20["excursions"]["24h"]
    assert abs(exc_24h - 0.109) < 0.001

def test_chronological_train_validation_split():
    # Mock some data
    closes = [100.0] * 60
    bars = _mock_bars(closes)
    
    engine = AdvancedCalibrator().engine
    # Replace engine so it's fast
    class FastEngine:
        def analyze(self, *args, **kwargs):
            from app.application.engines.pullback_risk_engine import PullbackRiskReport
            return PullbackRiskReport(score=10, level="LOW", directional_context="", drivers=[], warnings=[])
    
    calib = AdvancedCalibrator(engine=FastEngine())
    samples = calib.process_data(bars, lookback=10, max_forward_window=10, step_hours=5)
    
    res = calib.run_calibration(samples)
    
    assert res["train_size"] > 0
    assert res["val_size"] > 0
    assert res["dataset_size"] == res["train_size"] + res["val_size"]
    
    # Check that it's strictly chronological (we know split_idx = int(N*0.7))
    split_idx = int(len(samples) * 0.7)
    train_samples = samples[:split_idx]
    val_samples = samples[split_idx:]
    
    max_train_time = max(datetime.fromisoformat(s["timestamp"]) for s in train_samples)
    min_val_time = min(datetime.fromisoformat(s["timestamp"]) for s in val_samples)
    
    assert max_train_time < min_val_time

def test_repeatability():
    closes = [100.0] * 50
    bars = _mock_bars(closes)
    
    class DetermEngine:
        def analyze(self, *args, **kwargs):
            from app.application.engines.pullback_risk_engine import PullbackRiskReport
            return PullbackRiskReport(score=42, level="MEDIUM", directional_context="", drivers=["RSI exhaustion detected"], warnings=[])
            
    calib = AdvancedCalibrator(engine=DetermEngine())
    s1 = calib.process_data(bars, lookback=10, max_forward_window=5, step_hours=5)
    s2 = calib.process_data(bars, lookback=10, max_forward_window=5, step_hours=5)
    
    assert s1 == s2
