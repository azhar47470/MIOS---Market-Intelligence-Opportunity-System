from datetime import UTC, datetime

from app.domain.common import (
    ConfidenceScore,
    ContractStatus,
    EvidenceRecord,
    EvidenceStrength,
    RiskRecord,
)
from app.domain.features import InstitutionalFeatureSet
from app.domain.intelligence import DirectionalBias, EngineId, InstitutionalAnalysis
from app.domain.market_data import CotPositioningSnapshot, EtfFlowSnapshot
from app.features.institutional_features import build_institutional_features


class InstitutionalIntelligenceEngine:
    def analyze(
        self,
        cot_positioning: tuple[CotPositioningSnapshot, ...],
        gld_flow: EtfFlowSnapshot | None,
        provider_errors: dict[str, str] | None = None,
    ) -> InstitutionalAnalysis:
        return self.analyze_features(
            build_institutional_features(cot_positioning, gld_flow, provider_errors)
        )

    def analyze_features(self, features: InstitutionalFeatureSet) -> InstitutionalAnalysis:
        started_at = datetime.now(UTC)
        cot_score, cot_text = self._cot_score(
            features.latest_managed_money_net, features.cot_error
        )
        etf_score, etf_text = self._etf_score(
            features.gld_daily_ounce_change,
            features.gld_error,
            features.gld_total_ounces,
            features.gld_total_tonnes,
            features.gld_total_nav_usd,
            features.gld_shares_outstanding,
            features.gld_date,
        )
        available = features.source_count
        confidence = 35 + (available * 25)
        score = round((cot_score + etf_score) / 2)
        evidence = (
            EvidenceRecord(
                evidence_id="INST-COT-001",
                category="COT Positioning",
                description=cot_text,
                strength=(
                    EvidenceStrength.MEDIUM
                    if features.latest_managed_money_net is not None
                    else EvidenceStrength.LOW
                ),
                confidence=confidence,
                source="Institutional Intelligence Engine",
            ),
            EvidenceRecord(
                evidence_id="INST-ETF-001",
                category="ETF Flows",
                description=etf_text,
                strength=(
                    EvidenceStrength.MEDIUM
                    if features.gld_total_ounces is not None
                    else EvidenceStrength.LOW
                ),
                confidence=confidence,
                source="Institutional Intelligence Engine",
            ),
        )
        risks = ()
        if available < 2:
            risks = (
                RiskRecord(
                    risk=(
                        "Institutional view is incomplete because one or more "
                        "flow sources are unavailable."
                    ),
                    severity=EvidenceStrength.MEDIUM,
                    probability=65,
                ),
            )

        return InstitutionalAnalysis(
            engine=EngineId.INSTITUTIONAL,
            status=ContractStatus.SUCCESS if available else ContractStatus.NO_DATA,
            confidence=ConfidenceScore(
                value=confidence,
                reason="Institutional confidence reflects COT and GLD availability.",
            ),
            quality=confidence,
            score=score,
            bias=_bias_from_score(score),
            evidence=evidence,
            risks=risks,
            execution_ms=_elapsed_ms(started_at),
            positioning_summary=f"{cot_text} {etf_text}",
            etf_flow_score=etf_score,
            cot_score=cot_score,
        )

    def _cot_score(
        self, managed_money_net: int | None, error: str | None = None
    ) -> tuple[int, str]:
        if managed_money_net is None:
            description = f"COT data unavailable: {error}" if error else "COT data unavailable."
            return 50, description
        if managed_money_net > 50_000:
            return (
                65,
                f"Managed money is net long gold futures by {managed_money_net:,} contracts.",
            )
        if managed_money_net < -20_000:
            return (
                35,
                f"Managed money is net short gold futures by {abs(managed_money_net):,} contracts.",
            )
        return 50, f"Managed-money positioning is balanced at {managed_money_net:,} net contracts."

    def _etf_score(
        self,
        daily_ounce_change,
        error: str | None = None,
        total_ounces=None,
        total_tonnes=None,
        total_nav_usd=None,
        shares_outstanding=None,
        gld_date: str | None = None,
    ) -> tuple[int, str]:
        if daily_ounce_change is None:
            if total_ounces is not None:
                return (
                    55,
                    (
                        f"GLD holdings are {total_ounces:,.2f} ounces"
                        f"{_optional_metric(', ', total_tonnes, ' tonnes', 3)}"
                        f"{_optional_money(', total NAV ', total_nav_usd)}"
                        f"{_optional_metric(', shares outstanding ', shares_outstanding, '', 0)}"
                        f"{f' as of {gld_date}' if gld_date else ''}."
                    ),
                )
            description = (
                f"GLD flow delta unavailable: {error}"
                if error
                else "GLD flow delta unavailable."
            )
            return 50, description
        if daily_ounce_change > 0:
            return 65, f"GLD holdings rose by {daily_ounce_change:,.0f} ounces."
        if daily_ounce_change < 0:
            return 35, f"GLD holdings fell by {abs(daily_ounce_change):,.0f} ounces."
        return 50, "GLD holdings were unchanged."


def _bias_from_score(score: int) -> DirectionalBias:
    if score >= 60:
        return DirectionalBias.BULLISH
    if score <= 40:
        return DirectionalBias.BEARISH
    return DirectionalBias.NEUTRAL


def _elapsed_ms(started_at: datetime) -> int:
    return int((datetime.now(UTC) - started_at).total_seconds() * 1000)


def _optional_metric(prefix: str, value, suffix: str, decimals: int) -> str:
    if value is None:
        return ""
    return f"{prefix}{value:,.{decimals}f}{suffix}"


def _optional_money(prefix: str, value) -> str:
    if value is None:
        return ""
    return f"{prefix}${value:,.2f}"
