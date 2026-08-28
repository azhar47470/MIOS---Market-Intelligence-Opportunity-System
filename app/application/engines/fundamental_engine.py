from datetime import UTC, datetime
from decimal import Decimal

from app.domain.common import (
    ConfidenceScore,
    ContractStatus,
    EvidenceRecord,
    EvidenceStrength,
    RiskRecord,
)
from app.domain.features import MacroFeatureSet, MacroSeriesFeature
from app.domain.intelligence import DirectionalBias, EngineId, FundamentalAnalysis
from app.domain.market_data import EconomicCalendarEvent, MacroSeriesObservation
from app.features.macro_features import build_macro_features


class FundamentalIntelligenceEngine:
    def analyze(
        self,
        dxy_observations: tuple[MacroSeriesObservation, ...],
        economic_events: tuple[EconomicCalendarEvent, ...],
        provider_errors: dict[str, str] | None = None,
        macro_observations: tuple[MacroSeriesObservation, ...] = (),
    ) -> FundamentalAnalysis:
        return self.analyze_features(
            build_macro_features(
                dxy_observations,
                economic_events,
                provider_errors,
                macro_observations,
            )
        )

    def analyze_features(self, features: MacroFeatureSet) -> FundamentalAnalysis:
        started_at = datetime.now(UTC)
        dollar_bias, dollar_score, dxy_description = self._analyze_dxy(features)
        macro_evidence, macro_score_adjustment, macro_risks = self._macro_evidence(features)
        high_impact_events = features.high_impact_us_event_count
        event_penalty = min(15, high_impact_events * 5)
        score = _clamp_score(dollar_score + macro_score_adjustment - event_penalty)
        confidence = 75 if features.observation_count else 35
        confidence = min(90, confidence + min(15, len(features.macro_series) * 2))
        if high_impact_events:
            confidence = max(35, confidence - 10)

        evidence = [
            EvidenceRecord(
                evidence_id="FUND-DXY-001",
                category="US Dollar",
                description=dxy_description,
                strength=(
                    EvidenceStrength.HIGH if features.observation_count else EvidenceStrength.LOW
                ),
                confidence=confidence,
                source="Fundamental Intelligence Engine",
            ),
        ]
        evidence.extend(macro_evidence)
        if features.macro_surprise_count:
            evidence.append(
                EvidenceRecord(
                    evidence_id="FUND-SURPRISE-001",
                    category="Macro Surprise Analysis",
                    description=(
                        f"{features.macro_surprise_count} released calendar value(s) differ from "
                        "their available forecasts; assess direction before acting."
                    ),
                    strength=EvidenceStrength.MEDIUM,
                    confidence=max(40, confidence - 8),
                    source="Fundamental Intelligence Engine",
                )
            )
        evidence.append(
            EvidenceRecord(
                evidence_id="FUND-CENTRAL-BANK-001",
                category="Central Bank Gold Purchases",
                description=(
                    "No dedicated central-bank gold-purchase source is configured in Version 1."
                ),
                strength=EvidenceStrength.LOW,
                confidence=100,
                source="Fundamental Intelligence Engine",
            )
        )
        risks = []
        risks.extend(macro_risks)
        if high_impact_events:
            risks.append(
                RiskRecord(
                    risk=(
                        f"{high_impact_events} high-impact US macro event(s) "
                        "are near the current window."
                    ),
                    severity=EvidenceStrength.HIGH,
                    probability=70,
                )
            )
        if not features.observation_count:
            risks.append(
                RiskRecord(
                    risk="Dollar-strength evidence is missing; macro confidence is reduced.",
                    severity=EvidenceStrength.HIGH,
                    probability=80,
                )
            )
        if not features.macro_series:
            risks.append(
                RiskRecord(
                    risk=(
                        f"Expanded macro series are unavailable: {features.macro_error}"
                        if features.macro_error
                        else "Expanded macro series are unavailable; macro breadth is reduced."
                    ),
                    severity=EvidenceStrength.MEDIUM,
                    probability=70,
                )
            )

        return FundamentalAnalysis(
            engine=EngineId.FUNDAMENTAL,
            status=(
                ContractStatus.SUCCESS
                if features.observation_count
                else ContractStatus.PARTIAL_SUCCESS
            ),
            confidence=ConfidenceScore(
                value=confidence, reason="Macro confidence reflects DXY freshness and event risk."
            ),
            quality=confidence,
            score=score,
            bias=_bias_from_score(score),
            evidence=tuple(evidence),
            risks=tuple(risks),
            execution_ms=_elapsed_ms(started_at),
            macro_narrative=self._macro_narrative(
                dollar_bias,
                high_impact_events,
                features.macro_series,
            ),
            dollar_bias=dollar_bias,
            high_impact_event_count=high_impact_events,
        )

    def _analyze_dxy(self, features: MacroFeatureSet) -> tuple[DirectionalBias, int, str]:
        if features.dxy_change_percent is None:
            description = (
                f"DXY data is unavailable or insufficient: {features.dxy_error}"
                if features.dxy_error
                else "DXY data is unavailable or insufficient."
            )
            return DirectionalBias.UNKNOWN, 50, description
        change_pct = features.dxy_change_percent
        if change_pct <= Decimal("-0.15"):
            return (
                DirectionalBias.BULLISH,
                68,
                f"DXY weakened by {change_pct:.2f}%, supportive for gold.",
            )
        if change_pct >= Decimal("0.15"):
            return (
                DirectionalBias.BEARISH,
                35,
                f"DXY strengthened by {change_pct:.2f}%, a headwind for gold.",
            )
        return (
            DirectionalBias.NEUTRAL,
            52,
            f"DXY changed only {change_pct:.2f}%, giving limited macro signal.",
        )

    def _macro_evidence(
        self, features: MacroFeatureSet
    ) -> tuple[list[EvidenceRecord], int, list[RiskRecord]]:
        evidence: list[EvidenceRecord] = []
        risks: list[RiskRecord] = []
        adjustment = 0
        for series_id, label, inverse_for_gold in (
            ("FEDFUNDS", "Fed Policy", True),
            ("DFII10", "Real Yields", True),
            ("CPIAUCSL", "Inflation Trend", False),
            ("PAYEMS", "Employment Trend", True),
            ("GDPC1", "GDP Trend", True),
            ("NAPM", "PMI Trend", True),
            ("T10Y2Y", "Yield Curve", False),
        ):
            feature = features.macro_series.get(series_id)
            if feature is None or feature.latest_value is None:
                continue
            contribution, description = _macro_series_interpretation(
                label,
                feature,
                inverse_for_gold=inverse_for_gold,
            )
            adjustment += contribution
            evidence.append(
                EvidenceRecord(
                    evidence_id=f"FUND-{series_id}-001",
                    category=label,
                    description=description,
                    strength=EvidenceStrength.MEDIUM,
                    confidence=min(85, 50 + min(25, feature.observation_count)),
                    source="Fundamental Intelligence Engine",
                )
            )
        if "DFII10" not in features.macro_series:
            risks.append(
                RiskRecord(
                    risk="Real-yield evidence is unavailable; a core gold macro input is missing.",
                    severity=EvidenceStrength.HIGH,
                    probability=75,
                )
            )
        return evidence, max(-20, min(20, adjustment)), risks

    def _macro_narrative(
        self,
        dollar_bias: DirectionalBias,
        high_impact_events: int,
        macro_series: dict[str, MacroSeriesFeature],
    ) -> str:
        event_text = (
            f" {high_impact_events} high-impact US event(s) require caution."
            if high_impact_events
            else " No immediate high-impact US macro event is blocking normal analysis."
        )
        return (
            f"Macro stance is {dollar_bias.value.lower()} for gold based on "
            f"dollar evidence and {len(macro_series)} configured macro series.{event_text}"
        )


def _macro_series_interpretation(
    label: str,
    feature: MacroSeriesFeature,
    *,
    inverse_for_gold: bool,
) -> tuple[int, str]:
    change = feature.change_percent
    if change is None:
        return (
            0,
            f"{label} latest reading is {feature.latest_value}; no prior reading is available.",
        )
    direction = 1 if change > 0 else -1 if change < 0 else 0
    contribution = direction * (-3 if inverse_for_gold else 2)
    relation = "headwind" if contribution < 0 else "supportive" if contribution > 0 else "neutral"
    return (
        contribution,
        (
            f"{label} changed {change:.2f}% to {feature.latest_value}; current reading is "
            f"{relation} for gold."
        ),
    )


def _bias_from_score(score: int) -> DirectionalBias:
    if score >= 60:
        return DirectionalBias.BULLISH
    if score <= 40:
        return DirectionalBias.BEARISH
    return DirectionalBias.NEUTRAL


def _clamp_score(value: int) -> int:
    return max(0, min(100, int(value)))


def _elapsed_ms(started_at: datetime) -> int:
    return int((datetime.now(UTC) - started_at).total_seconds() * 1000)
