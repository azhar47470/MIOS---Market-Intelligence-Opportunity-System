"""Shared presentation content and helpers for the decision adapters.

Adapters re-express the same UnifiedDecision for different users. The narrative
and engine reason maps, plus the recommendation/conviction/horizon rules, live
here so every mode stays consistent and nothing drifts between adapters.
"""

NARRATIVE_REASONS = {
    "Central Bank Buying": "Central banks continue accumulating gold.",
    "Rate Cut Cycle": "Rate-cut expectations support non-yielding assets.",
    "Inflation Resurgence": "Inflation remains elevated, supporting hard assets.",
    "Middle East Escalation": "Geopolitical risk sustains safe-haven demand.",
    "De-dollarization": "De-dollarization trends support gold as a reserve asset.",
    "Higher for Longer": "The policy backdrop keeps real yields and gold in focus.",
    "Gold ETF Flows": "Investment flows into gold funds are supportive.",
    "Recession Fear": "Growth concerns favor a defensive allocation to gold.",
    "Dollar Weakness": "A softer dollar is a tailwind for gold.",
}

ENGINE_REASONS = {
    "geopolitical": "Geopolitical backdrop remains supportive.",
    "institutional": "Institutional demand is strong.",
    "macro": "Macro environment is supportive.",
    "fundamental": "Fundamentals are constructive.",
}

RISK_BY_CONFIDENCE = {0.75: "high", 0.55: "medium"}
HORIZON_LABELS = {"BULLISH": "2-4 weeks", "BEARISH": "1-2 weeks", "NEUTRAL": "Ongoing review"}


def recommendation_from(bias: str, confidence: float) -> str:
    if confidence < 0.5:
        return "HOLD"
    if bias == "BULLISH":
        return "STRONG BUY" if confidence >= 0.75 else "BUY"
    if bias == "BEARISH":
        return "SELL" if confidence >= 0.75 else "REDUCE"
    return "HOLD"


def conviction_from(confidence: float) -> str:
    if confidence >= 0.75:
        return "High"
    if confidence >= 0.55:
        return "Medium"
    return "Low"


def horizon_from(bias: str) -> str:
    return HORIZON_LABELS.get(bias, "Ongoing review")


def reasons_from(unified, max_n: int = 5) -> tuple[str, ...]:
    reasons: list[str] = []
    for narrative in unified.narratives:
        if narrative in NARRATIVE_REASONS:
            reasons.append(NARRATIVE_REASONS[narrative])
    for engine, direction in unified.engine_signals.items():
        if direction == "bullish" and engine in ENGINE_REASONS:
            reasons.append(ENGINE_REASONS[engine])
    if not reasons:
        if unified.market_bias.value == "BEARISH":
            reasons.append("Risk/reward has deteriorated; macro and demand signals are softer.")
        else:
            reasons.append("Signals are mixed; no strong directional edge right now.")
    seen: set[str] = set()
    out: list[str] = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            out.append(reason)
    return tuple(out[:max_n])
