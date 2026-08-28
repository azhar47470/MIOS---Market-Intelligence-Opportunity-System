import uuid
from datetime import datetime, UTC
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.domain.features import TechnicalFeatureSet, TechnicalSignalDirection, FairValueGap
from app.domain.common import EvidenceStrength
from app.domain.intelligence import (
    EvidenceRecord,
    MarketRegimeAnalysis,
    MarketRegime,
    PullbackRiskReport,
)
from app.domain.market_data import OhlcBar
from app.features.technical_features import build_technical_features

PullbackRiskLevel = Literal["LOW", "MEDIUM", "HIGH", "EXTREME"]

def report_to_evidence(report: PullbackRiskReport) -> list[EvidenceRecord]:
    strength = EvidenceStrength.LOW
    if report.level == "MEDIUM":
        strength = EvidenceStrength.MEDIUM
    elif report.level == "HIGH":
        strength = EvidenceStrength.HIGH
    elif report.level == "EXTREME":
        strength = EvidenceStrength.CRITICAL

    records = []
    # Main summary evidence
    records.append(
        EvidenceRecord(
            evidence_id=f"PULLBACK-RISK-{uuid.uuid4().hex[:6].upper()}",
            category="Pullback Risk",
            description=f"Pullback Risk Score: {report.score}/100. Level: {report.level}. {report.directional_context}",
            strength=strength,
            confidence=100,
            source="Pullback Risk Engine"
        )
    )
    
    # Add drivers as evidence
    for i, driver in enumerate(report.drivers):
        records.append(
            EvidenceRecord(
                evidence_id=f"PULLBACK-DRIVER-{uuid.uuid4().hex[:6].upper()}",
                category="Pullback Driver",
                description=driver,
                strength=strength,
                confidence=100,
                source="Pullback Risk Engine"
            )
        )

    return records


class PullbackRiskEngine:
    def analyze(self, bars: tuple[OhlcBar, ...], regime: MarketRegimeAnalysis) -> PullbackRiskReport:
        features = build_technical_features(bars)
        
        score = 0
        drivers = []
        warnings = []
        
        if features.candle_count < 5:
            return PullbackRiskReport(
                score=0,
                level="LOW",
                directional_context="Insufficient data for pullback risk.",
                drivers=["Insufficient candles"],
                warnings=["Insufficient data"]
            )
        
        # 1. RSI Exhaustion (max 20)
        rsi = features.rsi_14 or Decimal("50")
        if rsi >= Decimal("70"):
            points = min(20, int((rsi - Decimal("70")) * 2))
            score += points
            if points > 0:
                drivers.append(f"RSI(14) = {rsi:.2f} -> overbought")
        
        # 2. Resistance / FVG proximity (max 20)
        latest_close = features.latest_close or Decimal("0")
        res_points = 0
        if features.resistance and latest_close > 0:
            distance_to_res = (features.resistance - latest_close) / latest_close
            if distance_to_res < Decimal("0.005"):  # Within 0.5% of resistance
                res_points += 10
                drivers.append("Price near resistance")
        
        # Bearish FVG proximity
        for fvg in features.fair_value_gaps:
            if fvg.direction == TechnicalSignalDirection.BEARISH:
                if latest_close < fvg.lower_bound and (fvg.lower_bound - latest_close) / latest_close < Decimal("0.01"):
                    res_points += 10
                    drivers.append("Bearish FVG overhead")
                    break
        
        res_points = min(20, res_points)
        score += res_points

        # 3. Momentum deterioration (max 15)
        momentum = features.momentum_percent or Decimal("0")
        if momentum < Decimal("0"):
            score += 15
            drivers.append("Momentum weakening")
        elif momentum < Decimal("0.5"):
            score += 5
            drivers.append("Momentum flat")
            
        # 4. EMA / mean extension (max 10)
        ema200 = features.ema_200
        if ema200 and ema200 > 0:
            extension = (latest_close - ema200) / ema200
            if extension > Decimal("0.05"): # > 5% above EMA200
                score += 10
                drivers.append("Overextended above daily EMA(200)")
                
        # 5. Trend quality (max 10)
        # Low trend quality increases pullback risk
        tq = features.trend_quality
        if tq < 40:
            score += 10
            drivers.append("Weak trend quality")
            
        # 6. Market structure / liquidity (max 10)
        if features.liquidity_sweep:
            score += 10
            drivers.append("Recent liquidity sweep")
            
        # 7. Regime instability (max 10)
        if regime.regime in (MarketRegime.RANGE, MarketRegime.HIGH_VOLATILITY):
            score += 10
            drivers.append(f"Regime instability ({regime.regime.value})")
            
        # 8. Volatility condition (max 5)
        atr = features.average_true_range or Decimal("0")
        if atr > Decimal("0") and latest_close > Decimal("0"):
            vol_pct = atr / latest_close
            if vol_pct > Decimal("0.01"): # >1% hourly ATR
                score += 5
                drivers.append("Elevated volatility")

        # Cap score at 100
        score = min(100, max(0, score))
        
        level: PullbackRiskLevel = "LOW"
        if score >= 80:
            level = "EXTREME"
        elif score >= 60:
            level = "HIGH"
        elif score >= 30:
            level = "MEDIUM"
            
        context = "BULLISH trend with elevated correction risk" if score >= 60 else "Normal market conditions"
        
        return PullbackRiskReport(
            score=score,
            level=level,
            directional_context=context,
            drivers=drivers,
            warnings=warnings
        )
