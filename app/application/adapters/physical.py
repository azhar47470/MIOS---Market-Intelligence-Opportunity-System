"""Physical gold adapter — presents the outlook as an investment recommendation."""

from app.application.adapters.base import DecisionAdapter
from app.application.adapters.content import (
    conviction_from,
    horizon_from,
    NARRATIVE_REASONS,
    reasons_from,
    recommendation_from,
)
from app.domain.decisions import PhysicalGoldDecision, UnifiedDecision

_ACTIONS = {
    "STRONG BUY": "Accumulate aggressively",
    "BUY": "Accumulate on dips",
    "HOLD": "Hold current position / wait for clarity",
    "REDUCE": "Trim / take partial profits",
    "SELL": "Reduce exposure significantly",
}

_ALLOCATIONS = {
    "STRONG BUY": "Increase allocation significantly (e.g., +10-15% of your gold sleeve; 20% -> 35%)",
    "BUY": "Increase allocation moderately (e.g., +5-10%; 20% -> 28%)",
    "HOLD": "Maintain current allocation; no change recommended",
    "REDUCE": "Reduce allocation moderately (e.g., -5-10%); consider taking partial profits",
    "SELL": "Reduce allocation significantly (e.g., -15-25%)",
}


class PhysicalGoldAdapter(DecisionAdapter):
    @property
    def name(self) -> str:
        return "physical"

    def adapt(self, unified: UnifiedDecision, spot: float | None = None, is_actionable: bool = True) -> PhysicalGoldDecision:
        recommendation = recommendation_from(unified.market_bias.value, unified.confidence / 100)
        
        action = _ACTIONS.get(recommendation, "Hold current position")
        allocation = _ALLOCATIONS.get(recommendation, "Maintain current allocation")
        
        if not is_actionable:
            action = "WAIT"
            allocation = "Maintain current allocation; wait for stronger confirmation."
            
        return PhysicalGoldDecision(
            recommendation=recommendation,
            conviction=conviction_from(unified.confidence / 100),
            horizon=horizon_from(unified.market_bias.value),
            action=action,
            allocation_guidance=allocation,
            reasons=reasons_from(unified),
            thesis=_thesis(unified),
            confidence=unified.confidence,
            timestamp=unified.timestamp,
        )


def _thesis(unified: UnifiedDecision) -> str:
    bias_word = {
        "BULLISH": "constructive",
        "BEARISH": "deteriorating",
        "NEUTRAL": "balanced",
    }.get(unified.market_bias.value, "mixed")
    horizon = horizon_from(unified.market_bias.value)
    drivers = [
        NARRATIVE_REASONS[narrative].lower().rstrip(".")
        for narrative in unified.narratives
        if narrative in NARRATIVE_REASONS
    ][:3]
    if unified.market_bias.value == "BULLISH":
        text = f"The outlook for gold is {bias_word} over the next {horizon}."
        if drivers:
            text += " It is underpinned by: " + "; ".join(drivers) + "."
        text += " On the balance of evidence the committee is net positive for gold."
        return text
    if unified.market_bias.value == "BEARISH":
        return (
            f"The outlook for gold has turned {bias_word} over the next {horizon}. "
            "Risk and reward have deteriorated; consider reducing exposure and "
            "reassessing once signals clear."
        )
    return (
        f"The outlook for gold is {bias_word}. Signals are mixed with no strong "
        "directional edge; holding steady and waiting for clarity is the prudent course."
    )
