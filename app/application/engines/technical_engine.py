from datetime import UTC, datetime
from decimal import Decimal

from app.domain.common import (
    ConfidenceScore,
    ContractStatus,
    EvidenceRecord,
    EvidenceStrength,
    RiskRecord,
)
from app.domain.features import TechnicalFeatureSet, TechnicalSignalDirection
from app.domain.intelligence import DirectionalBias, EngineId, TechnicalAnalysis
from app.domain.market_data import OhlcBar
from app.domain.notification_models import PriceLevel, SupportResistanceLevels
from app.features.technical_features import build_technical_features


class TechnicalIntelligenceEngine:
    def __init__(self, stale_candle_threshold_minutes: int = 120) -> None:
        self.stale_candle_threshold_minutes = stale_candle_threshold_minutes

    def analyze(self, bars: tuple[OhlcBar, ...]) -> TechnicalAnalysis:
        return self.analyze_features(build_technical_features(bars))

    def analyze_features(self, features: TechnicalFeatureSet) -> TechnicalAnalysis:
        started_at = datetime.now(UTC)
        if features.candle_count < 5:
            return self._insufficient_data(started_at)

        latest_close = features.latest_close or Decimal("0")
        if latest_close <= 0:
            return self._insufficient_data(started_at)
        short_ma = features.short_moving_average or latest_close
        long_ma = features.long_moving_average or latest_close
        atr = features.average_true_range or Decimal("0")
        momentum_pct = features.momentum_percent or Decimal("0")
        trend_score = _clamp_score(50 + int((short_ma - long_ma) / latest_close * Decimal("1000")))
        momentum_score = _clamp_score(50 + int(momentum_pct * Decimal("8")))
        volatility_score = _clamp_score(int((atr / latest_close) * Decimal("10000")))
        structure_adjustment = _structure_adjustment(features)
        score = _clamp_score(
            round(
                (trend_score * 0.32)
                + (momentum_score * 0.24)
                + (features.trend_quality * 0.14)
                + 20
                + structure_adjustment
            )
        )
        bias = _bias_from_score(score)
        support = features.support or latest_close
        resistance = features.resistance or latest_close
        expected_move = max(atr * Decimal("2"), Decimal("1"))
        confidence_value = min(
            95 if features.multi_timeframe_aligned else 85,
            45
            + features.candle_count
            + (8 if features.multi_timeframe_aligned else 0)
            + (4 if features.volume_confirmation != TechnicalSignalDirection.NEUTRAL else 0),
        )

        evidence = [
            EvidenceRecord(
                evidence_id="TECH-TREND-001",
                category="Trend",
                description=f"Short moving average {short_ma:.2f} versus baseline {long_ma:.2f}.",
                strength=(
                    EvidenceStrength.HIGH
                    if abs(short_ma - long_ma) > atr
                    else EvidenceStrength.MEDIUM
                ),
                confidence=confidence_value,
                source="Technical Intelligence Engine",
            ),
            EvidenceRecord(
                evidence_id="TECH-MOM-001",
                category="Momentum",
                description=f"Five-bar momentum is {momentum_pct:.2f}%.",
                strength=EvidenceStrength.MEDIUM,
                confidence=max(50, confidence_value - 5),
                source="Technical Intelligence Engine",
            ),
        ]

        if features.rsi_14 is not None:
            evidence.append(
                EvidenceRecord(
                    evidence_id="TECH-RSI-001",
                    category="Momentum (RSI)",
                    description=f"Daily RSI(14) is {features.rsi_14:.2f}.",
                    strength=EvidenceStrength.HIGH if features.rsi_14 > 70 or features.rsi_14 < 30 else EvidenceStrength.MEDIUM,
                    confidence=confidence_value,
                    source="Technical Intelligence Engine",
                )
            )
        if features.ema_200 is not None:
            side = "above" if latest_close > features.ema_200 else "below"
            evidence.append(
                EvidenceRecord(
                    evidence_id="TECH-EMA200-001",
                    category="Macro Trend",
                    description=f"Price is {side} the Daily EMA(200) at {features.ema_200:.2f}.",
                    strength=EvidenceStrength.HIGH,
                    confidence=confidence_value,
                    source="Technical Intelligence Engine",
                )
            )
        if features.daily_trend is not None:
            evidence.append(
                EvidenceRecord(
                    evidence_id="TECH-DAILY-TREND-001",
                    category="Daily Timeframe Bias",
                    description=f"Daily timeframe bias is {features.daily_trend.value}.",
                    strength=EvidenceStrength.HIGH,
                    confidence=confidence_value,
                    source="Technical Intelligence Engine",
                )
            )
        evidence.extend(_structure_evidence(features, confidence_value))
        evidence.extend(_advanced_feature_evidence(features, confidence_value))
        
        risks_list = []
        if features.latest_timestamp:
            elapsed_minutes = (started_at - features.latest_timestamp).total_seconds() / 60.0
            if elapsed_minutes > self.stale_candle_threshold_minutes:
                risks_list.append(
                    RiskRecord(
                        risk="Technical candles are stale; recent price action is missing.",
                        severity=EvidenceStrength.MEDIUM,
                        probability=35,
                    )
                )
        
        risks = tuple(risks_list)
        return TechnicalAnalysis(
            engine=EngineId.TECHNICAL,
            status=ContractStatus.SUCCESS,
            confidence=ConfidenceScore(
                value=confidence_value,
                reason="Technical evidence derived from validated XAU/USD candles.",
            ),
            quality=confidence_value,
            score=score,
            bias=bias,
            evidence=tuple(evidence),
            risks=risks,
            execution_ms=_elapsed_ms(started_at),
            trend_strength=trend_score,
            momentum_score=momentum_score,
            volatility_score=volatility_score,
            support_resistance=SupportResistanceLevels(
                support=(PriceLevel(label="S1", price=support),),
                resistance=(PriceLevel(label="R1", price=resistance),),
            ),
            latest_close=latest_close,
            expected_move_usd=expected_move,
        )

    def _insufficient_data(self, started_at: datetime) -> TechnicalAnalysis:
        return TechnicalAnalysis(
            engine=EngineId.TECHNICAL,
            status=ContractStatus.NO_DATA,
            confidence=ConfidenceScore(value=0, reason="Insufficient XAU/USD candles."),
            quality=0,
            score=50,
            bias=DirectionalBias.UNKNOWN,
            evidence=(
                EvidenceRecord(
                    evidence_id="TECH-NODATA-001",
                    category="Data Availability",
                    description="Technical engine requires at least five XAU/USD candles.",
                    strength=EvidenceStrength.CRITICAL,
                    confidence=100,
                    source="Technical Intelligence Engine",
                ),
            ),
            risks=(
                RiskRecord(
                    risk="Cannot validate technical condition without recent candles.",
                    severity=EvidenceStrength.CRITICAL,
                    probability=100,
                ),
            ),
            execution_ms=_elapsed_ms(started_at),
            trend_strength=0,
            momentum_score=0,
            volatility_score=0,
            support_resistance=SupportResistanceLevels(),
        )


def _bias_from_score(score: int) -> DirectionalBias:
    if score >= 60:
        return DirectionalBias.BULLISH
    if score <= 40:
        return DirectionalBias.BEARISH
    return DirectionalBias.NEUTRAL


def _structure_adjustment(features: TechnicalFeatureSet) -> int:
    adjustment = 0
    if features.structure_signal is not None:
        adjustment += _direction_adjustment(features.structure_signal.direction, 12)
    if features.fair_value_gaps:
        adjustment += _direction_adjustment(features.fair_value_gaps[-1].direction, 5)
    if features.order_block is not None:
        adjustment += _direction_adjustment(features.order_block.direction, 5)
    if features.breaker_block is not None:
        adjustment += _direction_adjustment(features.breaker_block.direction, 3)
    if features.mitigation_block is not None:
        adjustment += _direction_adjustment(features.mitigation_block.direction, 2)
    if features.liquidity_sweep is not None:
        adjustment += _direction_adjustment(features.liquidity_sweep.direction, 5)
    if features.premium_discount is not None:
        if features.premium_discount.current_zone == "DISCOUNT":
            adjustment += 3
        elif features.premium_discount.current_zone == "PREMIUM":
            adjustment -= 3
    if features.vwap is not None and features.latest_close is not None:
        direction = (
            TechnicalSignalDirection.BULLISH
            if features.latest_close > features.vwap
            else TechnicalSignalDirection.BEARISH
        )
        adjustment += _direction_adjustment(direction, 4)
    if features.volume_confirmation != TechnicalSignalDirection.NEUTRAL:
        adjustment += _direction_adjustment(features.volume_confirmation, 4)
    if (
        features.asian_range is not None
        and features.asian_range.breakout_direction != TechnicalSignalDirection.NEUTRAL
    ):
        adjustment += _direction_adjustment(features.asian_range.breakout_direction, 4)
    if features.multi_timeframe_aligned:
        primary_bias = next(iter(features.timeframe_biases.values()))
        adjustment += _direction_adjustment(primary_bias, 6)
    return adjustment


def _direction_adjustment(direction: TechnicalSignalDirection, amount: int) -> int:
    if direction == TechnicalSignalDirection.BULLISH:
        return amount
    if direction == TechnicalSignalDirection.BEARISH:
        return -amount
    return 0


def _structure_evidence(
    features: TechnicalFeatureSet, confidence_value: int
) -> list[EvidenceRecord]:
    evidence: list[EvidenceRecord] = []
    if features.structure_signal is not None:
        signal = features.structure_signal
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-STRUCTURE-001",
                category="Market Structure",
                description=(
                    f"{signal.direction.value} {signal.signal_type} detected: close "
                    f"{signal.close:.2f} broke structure level {signal.broken_level:.2f}."
                ),
                strength=EvidenceStrength.HIGH,
                confidence=confidence_value,
                source="Technical Intelligence Engine",
            )
        )
    if features.fair_value_gaps:
        gap = features.fair_value_gaps[-1]
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-FVG-001",
                category="Fair Value Gap",
                description=(
                    f"{gap.direction.value} fair value gap between "
                    f"{gap.lower_bound:.2f} and {gap.upper_bound:.2f}."
                ),
                strength=EvidenceStrength.MEDIUM,
                confidence=max(45, confidence_value - 8),
                source="Technical Intelligence Engine",
            )
        )
    if features.order_block is not None:
        block = features.order_block
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-ORDERBLOCK-001",
                category="Order Block",
                description=(
                    f"{block.direction.value} order block zone from "
                    f"{block.low:.2f} to {block.high:.2f}."
                ),
                strength=EvidenceStrength.MEDIUM,
                confidence=max(45, confidence_value - 10),
                source="Technical Intelligence Engine",
            )
        )
    if features.asian_range is not None:
        asian_range = features.asian_range
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-ASIAN-RANGE-001",
                category="Asian Session Range",
                description=(
                    f"Asian range {asian_range.low:.2f}-{asian_range.high:.2f}; "
                    f"breakout is {asian_range.breakout_direction.value}."
                ),
                strength=(
                    EvidenceStrength.MEDIUM
                    if asian_range.breakout_direction != TechnicalSignalDirection.NEUTRAL
                    else EvidenceStrength.LOW
                ),
                confidence=max(40, confidence_value - 12),
                source="Technical Intelligence Engine",
            )
        )
    if features.timeframe_biases:
        alignment = "aligned" if features.multi_timeframe_aligned else "not aligned"
        bias_summary = ", ".join(
            f"{timeframe}={bias.value}" for timeframe, bias in features.timeframe_biases.items()
        )
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-MTF-001",
                category="Multi-Timeframe Alignment",
                description=f"Timeframe biases are {alignment}: {bias_summary}.",
                strength=(
                    EvidenceStrength.HIGH
                    if features.multi_timeframe_aligned
                    else EvidenceStrength.LOW
                ),
                confidence=max(40, confidence_value - 5),
                source="Technical Intelligence Engine",
            )
        )
    return evidence


def _advanced_feature_evidence(
    features: TechnicalFeatureSet, confidence_value: int
) -> list[EvidenceRecord]:
    evidence: list[EvidenceRecord] = []
    if features.swing_highs or features.swing_lows:
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-SWINGS-001",
                category="Swing Structure",
                description=(
                    f"Detected {len(features.swing_highs)} swing high(s) and "
                    f"{len(features.swing_lows)} swing low(s) in the active timeframe."
                ),
                strength=EvidenceStrength.MEDIUM,
                confidence=max(40, confidence_value - 8),
                source="Technical Intelligence Engine",
            )
        )
    if features.liquidity_sweep is not None:
        sweep = features.liquidity_sweep
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-LIQUIDITY-001",
                category="Liquidity Sweep",
                description=(
                    f"{sweep.direction.value} liquidity sweep reclaimed level "
                    f"{sweep.swept_level:.2f} with close {sweep.close:.2f}."
                ),
                strength=EvidenceStrength.HIGH,
                confidence=max(45, confidence_value - 4),
                source="Technical Intelligence Engine",
            )
        )
    if features.premium_discount is not None:
        zone = features.premium_discount
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-PREMIUM-DISCOUNT-001",
                category="Premium / Discount",
                description=(
                    f"Price is in {zone.current_zone} relative to range "
                    f"{zone.range_low:.2f}-{zone.range_high:.2f}; equilibrium is "
                    f"{zone.equilibrium:.2f}."
                ),
                strength=EvidenceStrength.MEDIUM,
                confidence=max(40, confidence_value - 10),
                source="Technical Intelligence Engine",
            )
        )
    for block, category, evidence_id in (
        (features.breaker_block, "Breaker Block", "TECH-BREAKER-001"),
        (features.mitigation_block, "Mitigation Block", "TECH-MITIGATION-001"),
    ):
        if block is not None:
            evidence.append(
                EvidenceRecord(
                    evidence_id=evidence_id,
                    category=category,
                    description=(
                        f"{block.direction.value} {block.block_type} zone spans "
                        f"{block.low:.2f}-{block.high:.2f}."
                    ),
                    strength=EvidenceStrength.MEDIUM,
                    confidence=max(40, confidence_value - 10),
                    source="Technical Intelligence Engine",
                )
    )
    if features.vwap is not None:
        side = (
            "above"
            if features.latest_close and features.latest_close > features.vwap
            else "below"
        )
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-VWAP-001",
                category="VWAP",
                description=(
                    f"Latest price is {side} volume-weighted average price "
                    f"{features.vwap:.2f}."
                ),
                strength=EvidenceStrength.MEDIUM,
                confidence=max(40, confidence_value - 8),
                source="Technical Intelligence Engine",
            )
        )
    if features.volume_ratio is not None:
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-VOLUME-001",
                category="Volume Confirmation",
                description=(
                    f"Latest volume is {features.volume_ratio:.2f}x the recent baseline; "
                    f"confirmation is {features.volume_confirmation.value}."
                ),
                strength=(
                    EvidenceStrength.HIGH
                    if features.volume_confirmation != TechnicalSignalDirection.NEUTRAL
                    else EvidenceStrength.LOW
                ),
                confidence=max(35, confidence_value - 12),
                source="Technical Intelligence Engine",
            )
        )
    evidence.append(
        EvidenceRecord(
            evidence_id="TECH-VOLATILITY-001",
            category="Volatility Regime",
            description=f"ATR-derived volatility regime is {features.volatility_regime}.",
            strength=EvidenceStrength.MEDIUM,
            confidence=max(40, confidence_value - 6),
            source="Technical Intelligence Engine",
        )
    )
    evidence.append(
        EvidenceRecord(
            evidence_id="TECH-TREND-QUALITY-001",
            category="Trend Quality",
            description=f"Trend quality is {features.trend_quality}/100.",
            strength=(
                EvidenceStrength.HIGH if features.trend_quality >= 70 else EvidenceStrength.MEDIUM
            ),
            confidence=max(40, confidence_value - 5),
            source="Technical Intelligence Engine",
        )
    )
    evidence.append(
        EvidenceRecord(
            evidence_id="TECH-LEVEL-CONFIDENCE-001",
            category="Support / Resistance Confidence",
            description=(
                f"Support confidence is {features.support_confidence}/100 and resistance "
                f"confidence is {features.resistance_confidence}/100."
            ),
            strength=EvidenceStrength.MEDIUM,
            confidence=max(40, confidence_value - 8),
            source="Technical Intelligence Engine",
        )
    )
    if features.higher_timeframe_confirmed:
        evidence.append(
            EvidenceRecord(
                evidence_id="TECH-HTF-001",
                category="Higher Timeframe Confirmation",
                description="H1 and H4 directional biases agree and are actionable.",
                strength=EvidenceStrength.HIGH,
                confidence=confidence_value,
                source="Technical Intelligence Engine",
            )
        )
    return evidence


def _clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


def _elapsed_ms(started_at: datetime) -> int:
    return int((datetime.now(UTC) - started_at).total_seconds() * 1000)
