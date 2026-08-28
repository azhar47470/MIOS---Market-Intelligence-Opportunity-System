from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.application.engines.technical_engine import TechnicalIntelligenceEngine
from app.domain.features import TechnicalSignalDirection
from app.domain.market_data import DataProviderId, MarketSymbol, OhlcBar, Timeframe
from app.domain.common import EvidenceStrength
from app.domain.features import TechnicalFeatureSet
from app.features.technical_features import build_technical_features


def test_technical_features_detect_bos_fvg_order_block_asian_breakout_and_mtf_alignment():
    bars = _clear_bullish_structure_bars() + _bullish_h4_bars()

    features = build_technical_features(bars)

    assert features.structure_signal is not None
    assert features.structure_signal.signal_type == "BOS"
    assert features.structure_signal.direction == TechnicalSignalDirection.BULLISH
    assert features.fair_value_gaps
    assert features.fair_value_gaps[-1].direction == TechnicalSignalDirection.BULLISH
    assert features.order_block is not None
    assert features.order_block.direction == TechnicalSignalDirection.BULLISH
    assert features.asian_range is not None
    assert features.asian_range.breakout_direction == TechnicalSignalDirection.BULLISH
    assert features.multi_timeframe_aligned is True
    assert features.timeframe_biases["1h"] == TechnicalSignalDirection.BULLISH
    assert features.timeframe_biases["4h"] == TechnicalSignalDirection.BULLISH


def test_technical_engine_emits_distinct_evidence_for_bos_event():
    bars = _clear_bullish_structure_bars() + _bullish_h4_bars()

    result = TechnicalIntelligenceEngine().analyze(bars)

    categories = {evidence.category for evidence in result.evidence}
    assert "Market Structure" in categories
    assert "Fair Value Gap" in categories
    assert "Order Block" in categories
    assert "Asian Session Range" in categories
    assert "Multi-Timeframe Alignment" in categories
    structure_evidence = next(
        evidence for evidence in result.evidence if evidence.category == "Market Structure"
    )
    assert "BULLISH BOS detected" in structure_evidence.description


def test_technical_engine_emits_advanced_liquidity_volume_and_level_evidence():
    h1 = list(_clear_bullish_structure_bars())
    h1 = [bar.model_copy(update={"volume": Decimal("1000")}) for bar in h1]
    h1[-1] = h1[-1].model_copy(
        update={
            "open": Decimal("108"),
            "high": Decimal("112"),
            "low": Decimal("100"),
            "close": Decimal("104"),
            "volume": Decimal("3000"),
        }
    )
    bars = tuple(h1) + _bullish_h4_bars()

    features = build_technical_features(bars)
    result = TechnicalIntelligenceEngine().analyze_features(features)

    assert features.liquidity_sweep is not None
    assert features.vwap is not None
    assert features.volume_ratio is not None
    assert features.support_confidence > 0
    categories = {evidence.category for evidence in result.evidence}
    assert {
        "Liquidity Sweep",
        "Premium / Discount",
        "VWAP",
        "Volume Confirmation",
        "Volatility Regime",
        "Trend Quality",
        "Support / Resistance Confidence",
        "Higher Timeframe Confirmation",
    } <= categories


def _clear_bullish_structure_bars() -> tuple[OhlcBar, ...]:
    start = datetime(2026, 7, 5, 0, 0, tzinfo=UTC)
    rows = (
        ("98", "100", "96", "98"),
        ("101", "102", "97", "101"),
        ("104", "106", "98", "104"),
        ("100", "103", "95", "96"),
        ("97", "101", "94", "95"),
        ("99", "102", "96", "100"),
        ("101", "104", "97", "103"),
        ("102", "103", "96", "97"),
        ("103", "105", "97", "104"),
        ("103", "104", "98", "101"),
        ("102", "103", "97", "100"),
        ("101", "104", "96", "99"),
        ("100", "103", "95", "97"),
        ("98", "102", "94", "96"),
        ("99", "103", "96", "102"),
        ("102", "104", "98", "103"),
        ("103", "105", "99", "104"),
        ("104", "104", "100", "103"),
        ("106", "108", "106", "107"),
        ("105", "109", "103", "108"),
    )
    return tuple(
        _bar(
            timestamp=start + timedelta(hours=index),
            timeframe=Timeframe.ONE_HOUR,
            open_=Decimal(open_),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
        )
        for index, (open_, high, low, close) in enumerate(rows)
    )


def _bullish_h4_bars() -> tuple[OhlcBar, ...]:
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    bars = []
    for index in range(20):
        close = Decimal("100") + Decimal(index)
        bars.append(
            _bar(
                timestamp=start + timedelta(hours=index * 4),
                timeframe=Timeframe.FOUR_HOURS,
                open_=close - Decimal("1"),
                high=close + Decimal("2"),
                low=close - Decimal("2"),
                close=close,
            )
        )
    return tuple(bars)


def _bar(
    *,
    timestamp: datetime,
    timeframe: Timeframe,
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
) -> OhlcBar:
    return OhlcBar(
        symbol=MarketSymbol.XAU_USD,
        provider_symbol="XAU/USD",
        timeframe=timeframe,
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        provider=DataProviderId.TWELVE_DATA,
    )

def test_technical_engine_fresh_candles_no_warning():
    from datetime import datetime, timedelta, UTC
    now = datetime.now(UTC)
    bars = tuple(
        OhlcBar(
            symbol=MarketSymbol.XAU_USD,
            provider_symbol="XAU/USD",
            timeframe=Timeframe.ONE_HOUR,
            timestamp=now - timedelta(minutes=10 * i),
            open=Decimal("1900"),
            high=Decimal("1910"),
            low=Decimal("1890"),
            close=Decimal("1905"),
            provider=DataProviderId.TWELVE_DATA,
        )
        for i in range(5, -1, -1)
    )
    engine = TechnicalIntelligenceEngine(stale_candle_threshold_minutes=60)
    result = engine.analyze(bars)
    
    stale_risks = [r for r in result.risks if "stale" in r.risk.lower()]
    assert len(stale_risks) == 0, "Expected no stale warning for fresh candles"

def test_technical_engine_stale_candles_medium_warning():
    from datetime import datetime, timedelta, UTC
    now = datetime.now(UTC)
    bars = tuple(
        OhlcBar(
            symbol=MarketSymbol.XAU_USD,
            provider_symbol="XAU/USD",
            timeframe=Timeframe.ONE_HOUR,
            timestamp=now - timedelta(hours=5) - timedelta(minutes=10 * i),
            open=Decimal("1900"),
            high=Decimal("1910"),
            low=Decimal("1890"),
            close=Decimal("1905"),
            provider=DataProviderId.TWELVE_DATA,
        )
        for i in range(5, -1, -1)
    )
    engine = TechnicalIntelligenceEngine(stale_candle_threshold_minutes=60)
    result = engine.analyze(bars)
    
    stale_risks = [r for r in result.risks if "stale" in r.risk.lower()]
    assert len(stale_risks) == 1
    assert stale_risks[0].severity == EvidenceStrength.MEDIUM

def test_technical_engine_insufficient_candles_critical_warning():
    bars = tuple()
    engine = TechnicalIntelligenceEngine()
    result = engine.analyze(bars)
    
    insufficient_risks = [r for r in result.risks if "without recent candles" in r.risk.lower()]
    assert len(insufficient_risks) == 1
    assert insufficient_risks[0].severity == EvidenceStrength.CRITICAL

def test_technical_engine_invalid_latest_close_critical_warning():
    from datetime import datetime, timedelta, UTC
    now = datetime.now(UTC)
    # Mock TechnicalFeatureSet with 0 close
    features = TechnicalFeatureSet(candle_count=10, latest_close=Decimal("0"), latest_timestamp=now)
    engine = TechnicalIntelligenceEngine()
    result = engine.analyze_features(features)
    
    insufficient_risks = [r for r in result.risks if "without recent candles" in r.risk.lower()]
    assert len(insufficient_risks) == 1
    assert insufficient_risks[0].severity == EvidenceStrength.CRITICAL
