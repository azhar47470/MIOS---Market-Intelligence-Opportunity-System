"""Gold ETF adapter — presents the outlook for gold ETF investors (GLD/IAU/GLDM)."""

from app.application.adapters.base import DecisionAdapter
from app.application.adapters.content import (
    conviction_from,
    horizon_from,
    reasons_from,
    recommendation_from,
)
from app.domain.decisions import ETFDecision, UnifiedDecision

_ACTIONS = {
    "STRONG BUY": "Build / add to a core gold ETF position",
    "BUY": "Add to gold ETF holdings on pullbacks",
    "HOLD": "Maintain current gold ETF allocation",
    "REDUCE": "Trim gold ETF holdings / take partial profits",
    "SELL": "Reduce gold ETF exposure significantly",
}

_ALLOCATIONS = {
    "STRONG BUY": "Increase gold ETF sleeve significantly (e.g., +10-15% of portfolio; 10% -> 22%)",
    "BUY": "Increase gold ETF sleeve moderately (e.g., +5-10%; 10% -> 18%)",
    "HOLD": "Maintain current gold ETF allocation; no change recommended",
    "REDUCE": "Reduce gold ETF sleeve moderately (e.g., -5-10%); take partial profits",
    "SELL": "Reduce gold ETF sleeve significantly (e.g., -15-25%)",
}


class GoldETFAdapter(DecisionAdapter):
    @property
    def name(self) -> str:
        return "etf"

    def adapt(self, unified: UnifiedDecision, spot: float | None = None, is_actionable: bool = True) -> ETFDecision:
        recommendation = recommendation_from(unified.market_bias.value, unified.confidence / 100)
        
        action = _ACTIONS.get(recommendation, "Maintain current gold ETF allocation")
        allocation = _ALLOCATIONS.get(recommendation, "Maintain current gold ETF allocation")
        
        if not is_actionable:
            action = "WAIT"
            allocation = "Maintain current ETF allocation; wait for stronger confirmation."

        return ETFDecision(
            recommendation=recommendation,
            conviction=conviction_from(unified.confidence / 100),
            horizon=horizon_from(unified.market_bias.value),
            action=action,
            vehicle_guidance=_vehicle(recommendation),
            flow_context=_flow_context(unified),
            allocation_guidance=allocation,
            reasons=reasons_from(unified),
            thesis=_thesis(unified),
            confidence=unified.confidence,
            timestamp=unified.timestamp,
        )


def _vehicle(recommendation: str) -> str:
    if recommendation in ("STRONG BUY", "BUY"):
        return (
            "Core physically-backed vehicles: GLD (0.40% fee, deepest liquidity - best for "
            "active trading), IAU (0.25%, balanced), GLDM (0.10%, lowest cost - best for "
            "buy-and-hold). Check premium/discount to NAV before entering; prefer trading "
            "near NAV."
        )
    if recommendation == "HOLD":
        return (
            "Hold existing GLD/IAU/GLDM positions. No new purchases needed; periodically "
            "review expense ratios and the fund premium/discount to NAV."
        )
    return (
        "To reduce exposure, sell ETF shares - GLD and IAU are highly liquid with tight "
        "bid/ask spreads. Review tax treatment first (gold ETFs may be taxed as collectibles)."
    )


def _flow_context(unified: UnifiedDecision) -> str:
    if "Gold ETF Flows" in unified.narratives:
        return (
            "ETF flows are supportive: gold funds are seeing net inflows, which typically "
            "reinforces price momentum."
        )
    return (
        "ETF flow backdrop is neutral; monitor GLD/IAU creation and redemption activity "
        "for confirmation of the trend."
    )


def _thesis(unified: UnifiedDecision) -> str:
    bias_word = {
        "BULLISH": "constructive",
        "BEARISH": "deteriorating",
        "NEUTRAL": "balanced",
    }.get(unified.market_bias.value, "mixed")
    horizon = horizon_from(unified.market_bias.value)
    if unified.market_bias.value == "BULLISH":
        return (
            f"The outlook for gold is {bias_word} over the next {horizon}, which supports "
            "adding to a physically-backed gold ETF position. ETF flows and the macro "
            "backdrop reinforce the case; build the position in tranches rather than all "
            "at once."
        )
    if unified.market_bias.value == "BEARISH":
        return (
            f"The outlook for gold has turned {bias_word} over the next {horizon}. "
            "Risk and reward for gold ETF holdings have deteriorated; consider trimming "
            "and reassessing once the picture clears."
        )
    return (
        f"The outlook for gold is {bias_word}. With no strong directional edge, holding "
        "the current gold ETF allocation and waiting for clarity is the prudent course."
    )
