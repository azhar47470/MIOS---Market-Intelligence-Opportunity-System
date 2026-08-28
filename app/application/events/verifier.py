"""Cross-source verification — confirm events from an authoritative outlet plus a
corroborator.

Port of the mios_v2 Stage 10 verifier onto the GIP domain. An event is confirmed when
an authoritative source (tier <= 2) reported it AND at least one other distinct source
corroborates it, so low-trust volume alone never confirms anything. Confidence scales
with corroboration breadth and tier diversity.
"""

import logging

from app.domain.intelligence import MarketEvent

logger = logging.getLogger("mios.events")

AUTHORITATIVE_MAX_TIER = 2

# Curated outlet tiers (lowercase names). Tier 1-2 are authoritative outlets that can
# anchor confirmation; tier 3-4 are credible financial media/industry outlets; anything
# unknown (aggregators, syndication, other) defaults to tier 5 and can only corroborate.
SOURCE_TIERS = {
    "reuters": 1,
    "bloomberg": 1,
    "associated press": 1,
    "ap": 1,
    "agence france-presse": 1,
    "afp": 1,
    "kyodo news": 1,
    "fed": 1,
    "ecb": 1,
    "imf": 1,
    "bis": 1,
    "treasury": 1,
    "wgc": 1,
    "cftc": 1,
    "lbma": 1,
    "federal reserve": 1,
    "world gold council": 1,
    "bank of england": 1,
    "bank of japan": 1,
    "boj": 1,
    "peoples bank of china": 1,
    "pboc": 1,
    "financial times": 2,
    "ft": 2,
    "wall street journal": 2,
    "wsj": 2,
    "new york times": 2,
    "nytimes": 2,
    "the guardian": 2,
    "bbc": 2,
    "bbc news": 2,
    "cnbc": 2,
    "finnhub": 2,
    "cbs news": 2,
    "nbc news": 2,
    "cnn": 2,
    "washington post": 2,
    "npr": 2,
    "al jazeera": 2,
    "barrons": 2,
    "the economist": 2,
    "economist": 2,
    "forbes": 2,
    "fortune": 2,
    "axios": 2,
    "the hill": 2,
    "sky news": 2,
    "france 24": 2,
    "deutsche welle": 2,
    "marketwatch": 3,
    "investing.com": 3,
    "forexlive": 3,
    "kitco": 3,
    "kitco news": 3,
    "mining.com": 3,
    "the street": 3,
    "google news": 3,
    "google_news": 3,
    "google_rss": 3,
    "marketaux": 3,
    "zero hedge": 3,
    "zerohedge": 3,
    "moneycontrol": 3,
    "economic times": 3,
    "times of india": 3,
    "hindu business": 3,
    "livemint": 3,
    "thestreet": 3,
    "benzinga": 3,
    "seeking alpha": 3,
    "zacks": 3,
    "thenewsapi": 4,
    "worldnewsapi": 4,
    "rss_bridge": 5,
}

# v2 publisher lists used for substring fallback when the exact outlet name is
# unknown (many Google News RSS / discovery API items carry variant publisher names).
_PUBLISHER_SUBSTRINGS = {
    1: [
        "federal reserve", "fed", "ecb", "imf", "bis", "treasury",
        "world gold council", "cftc", "lbma", "bank of england",
        "bank of japan", "peoples bank of china",
    ],
    2: [
        "financial times", "wall street journal", "new york times",
        "washington post", "associated press", "cbs news", "nbc news",
        "cnn", "bbc", "guardian", "npr", "al jazeera", "barrons",
        "reuters", "bloomberg", "finnhub", "axios", "sky news",
        "france 24", "deutsche welle",
    ],
    3: [
        "marketwatch", "investing.com", "forexlive", "kitco", "mining.com",
        "zero hedge", "moneycontrol", "economic times", "times of india",
        "hindu business", "livemint", "thestreet", "benzinga", "seeking alpha",
        "zacks", "google news",
    ],
}


def _resolve_tier(source: str) -> int:
    """Exact source-tier lookup first, then v2 substring publisher matching."""
    if not source:
        return 5
    key = source.strip().lower()
    exact = SOURCE_TIERS.get(key)
    if exact is not None:
        return exact
    padded = f" {key} "
    for tier, names in _PUBLISHER_SUBSTRINGS.items():
        for name in names:
            if name in padded:
                return tier
    return 5


class CrossSourceVerifier:
    def verify(self, events: tuple[MarketEvent, ...]) -> tuple[MarketEvent, ...]:
        confirmed = 0
        verified: list[MarketEvent] = []
        for event in events:
            sources = tuple(dict.fromkeys(event.sources))
            source_count = len(sources)
            tiers = [_resolve_tier(source) for source in sources]
            best_tier = min(tiers) if tiers else 5
            tier_diversity = len(set(tiers))
            has_authoritative = best_tier <= AUTHORITATIVE_MAX_TIER

            source_bonus = min(0.25, max(0, source_count - 1) * 0.06)
            authoritative_bonus = 0.15 if has_authoritative else 0.0
            diversity_bonus = min(0.15, max(0, tier_diversity - 1) * 0.05)
            confidence = min(
                1.0,
                round(
                    event.confidence + source_bonus + authoritative_bonus + diversity_bonus,
                    3,
                ),
            )
            is_confirmed = source_count >= 2 and has_authoritative
            if is_confirmed:
                confirmed += 1
            verified.append(
                event.model_copy(
                    update={
                        "sources": sources,
                        "confidence": confidence,
                        "is_confirmed": is_confirmed,
                        "best_tier": best_tier,
                        "tier_diversity": tier_diversity,
                        "has_authoritative": has_authoritative,
                    }
                )
            )
        logger.info("CrossSourceVerifier: %d/%d events confirmed", confirmed, len(events))
        return tuple(verified)
