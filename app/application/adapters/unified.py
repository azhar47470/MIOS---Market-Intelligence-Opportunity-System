"""Builds the UnifiedDecision — the canonical market outlook from the final decision,
committee votes, verified narratives, and engine signals."""

from datetime import UTC, datetime

from app.domain.ai import ResearchDeskReport
from app.domain.decisions import UnifiedDecision
from app.domain.enums import Recommendation
from app.domain.intelligence import AnalysisBundle, DecisionReport, DirectionalBias

_BIAS_BY_RECOMMENDATION = {
    Recommendation.STRONG_BUY: DirectionalBias.BULLISH,
    Recommendation.BUY: DirectionalBias.BULLISH,
    Recommendation.STRONG_SELL: DirectionalBias.BEARISH,
    Recommendation.TAKE_PROFIT: DirectionalBias.BEARISH,
}

_ENGINE_IDS = ("technical", "fundamental", "institutional", "news", "geopolitical", "regime")


class UnifiedDecisionBuilder:
    """Wraps the final decision report into the canonical market outlook.

    The decision engine speaks in recommendations; this translates that into a
    market bias (BULLISH/BEARISH/NEUTRAL) plus every piece of context the
    adapters need — active narratives, top evidence, committee votes, and engine
    reads. This is the single source of truth downstream.
    """

    def build(
        self,
        *,
        decision: DecisionReport,
        bundle: AnalysisBundle,
        research: ResearchDeskReport | None = None,
    ) -> UnifiedDecision:
        bias = _BIAS_BY_RECOMMENDATION.get(decision.recommendation, DirectionalBias.NEUTRAL)
        confidence = decision.confidence
        risk = "high" if confidence > 75 else "medium" if confidence > 55 else "low"
        active = tuple(
            narrative.name
            for narrative in bundle.market_data.narratives
            if narrative.strength > 0.3
        )
        evidence = _top_evidence(research)
        votes = research.committee_report.committee_votes if research is not None else ()
        signals = {
            engine_id: getattr(bundle, engine_id).bias.value.lower()
            for engine_id in _ENGINE_IDS
        }
        consensus = (
            research.committee_report.summary.split(" ", 1)[0].lower()
            if research is not None
            else "none"
        )
        return UnifiedDecision(
            market_bias=bias,
            confidence=confidence,
            risk=risk,
            narratives=active,
            evidence=evidence,
            committee_votes=votes,
            engine_signals=signals,
            reasoning=self._reasoning(bias, confidence, active, signals, consensus),
            timestamp=datetime.now(UTC),
        )

    def _reasoning(
        self,
        bias: DirectionalBias,
        confidence: int,
        narratives: tuple[str, ...],
        signals: dict[str, str],
        consensus: str,
    ) -> str:
        parts = [
            f"Gold outlook is {bias.value.lower()} at {confidence}% confidence "
            f"(committee consensus: {consensus})."
        ]
        if narratives:
            parts.append(f"Dominant narratives: {', '.join(narratives[:3])}.")
        directional = [f"{key} {value}" for key, value in signals.items() if value != "neutral"]
        if directional:
            parts.append(f"Engine read: {'; '.join(directional)}.")
        return " ".join(parts)


def _top_evidence(research: ResearchDeskReport | None) -> tuple[str, ...]:
    if research is None:
        return ()
    claims = [
        (item.confidence, f"[{item.category}] {item.claim}")
        for report in research.analyst_reports
        for item in report.structured_evidence
    ]
    claims.sort(key=lambda pair: pair[0], reverse=True)
    seen: set[str] = set()
    out: list[str] = []
    for _confidence, claim in claims:
        if claim not in seen:
            seen.add(claim)
            out.append(claim)
        if len(out) >= 5:
            break
    return tuple(out)
