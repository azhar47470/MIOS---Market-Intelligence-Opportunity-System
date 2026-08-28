"""Narrative clustering — assemble events into durable market narratives.

Port of the mios_v2 Stage 9 clusterer onto the GIP domain. Keyword templates match
against each event's title and summary; narrative strength is calibrated from event
count, source breadth, event confidence, and article volume, and ids are stable so a
narrative can be tracked across cycles (and attributed to paper-trading outcomes).
"""

from hashlib import md5
import logging
import re

from app.domain.intelligence import MarketEvent, MarketNarrative

logger = logging.getLogger("mios.events")

NARRATIVE_TEMPLATES = {
    "Higher for Longer": {
        "keywords": ["rate", "fed", "hawkish", "inflation persistent", "no cut"],
        "description": "Central banks maintaining restrictive policy",
    },
    "Rate Cut Cycle": {
        "keywords": ["rate cut", "dovish", "easing", "pivot", "lower rates"],
        "description": "Central banks beginning or continuing easing",
    },
    "Middle East Escalation": {
        "keywords": ["iran", "israel", "war", "strike", "red sea", "houthi"],
        "description": "Geopolitical escalation in Middle East",
    },
    "De-dollarization": {
        "keywords": ["dedollar", "brics", "reserve currency", "yuan", "gold reserves"],
        "description": "Shift away from USD dominance",
    },
    "Inflation Resurgence": {
        "keywords": ["inflation", "cpi", "price pressure", "hot inflation"],
        "description": "Inflation reaccelerating",
    },
    "Recession Fear": {
        "keywords": ["recession", "slowdown", "contraction", "yield curve inversion"],
        "description": "Growing recession concerns",
    },
    "Gold ETF Flows": {
        "keywords": ["etf", "inflows", "outflows", "spdr", "holdings"],
        "description": "Institutional gold ETF positioning shifts",
    },
    "Central Bank Buying": {
        "keywords": ["central bank purchase", "gold reserves", "pboc gold", "buying"],
        "description": "Sovereign gold accumulation",
    },
    "Dollar Weakness": {
        "keywords": ["dollar weak", "dxy fall", "dollar decline", "greenback"],
        "description": "USD depreciation supporting gold",
    },
}

def _compile_template_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Word-boundary matching so short keywords cannot match inside unrelated words
    ("easing" in "increasing", "rate" in "moderate", "war" in "toward"). A trailing
    "s" is allowed so singular keywords still match their common plural form."""
    alternatives = "|".join(
        re.escape(keyword) + ("s?" if keyword[-1].isalpha() and keyword[-1] != "s" else "")
        for keyword in keywords
    )
    return re.compile(rf"(?<![a-z0-9])(?:{alternatives})(?![a-z0-9])", re.IGNORECASE)


_TEMPLATE_PATTERNS = {
    name: _compile_template_pattern(template["keywords"])
    for name, template in NARRATIVE_TEMPLATES.items()
}


class NarrativeClusterer:
    def cluster(
        self,
        events: tuple[MarketEvent, ...],
        articles,
    ) -> tuple[MarketNarrative, ...]:
        events_by_id = {event.event_id: event for event in events}
        narratives: list[MarketNarrative] = []
        for name, pattern in _TEMPLATE_PATTERNS.items():
            matched_events = [
                event
                for event in events
                if pattern.search(f"{event.title} {event.summary}")
            ]
            if not matched_events:
                continue
            sources: set[str] = set()
            for event in matched_events:
                sources.update(event.sources)
            average_confidence = sum(
                event.confidence for event in matched_events
            ) / len(matched_events)
            article_ids = tuple(
                dict.fromkeys(
                    article_id
                    for event in matched_events
                    for article_id in event.article_ids
                )
            )
            strength = _clamp(
                0.20
                + 0.20 * min(len(matched_events) / 3.0, 1.0)
                + 0.20 * min(len(sources) / 3.0, 1.0)
                + 0.20 * average_confidence
                + 0.20 * min(len(article_ids) / 15.0, 1.0)
            )
            narratives.append(
                MarketNarrative(
                    narrative_id=_narrative_id(name),
                    name=name,
                    description=NARRATIVE_TEMPLATES[name]["description"],
                    event_ids=tuple(event.event_id for event in matched_events),
                    article_ids=article_ids,
                    strength=round(strength, 3),
                )
            )
        narratives.sort(key=lambda narrative: narrative.strength, reverse=True)
        logger.info("NarrativeClusterer: %d narratives detected", len(narratives))
        return tuple(narratives)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _narrative_id(name: str) -> str:
    digest = md5(name.encode("utf-8")).hexdigest()
    return f"NAR-{digest[:16]}"
