"""Gold Relevance Engine — v2 Stage 7. How important is an article for gold."""

from __future__ import annotations

from app.infrastructure.news.article import Article

DIRECT_SIGNALS = [
    "gold", "bullion", "xau", "precious metal", "gold price", "gold etf",
    "spdr gold", "gold mining",
]
MACRO_SIGNALS = [
    "federal reserve", "fed", "interest rate", "inflation", "cpi", "dollar",
    "dxy", "treasury", "real yield", "monetary policy", "rate cut", "rate hike",
]
GEO_SIGNALS = [
    "war", "sanctions", "geopolitical", "crisis", "conflict", "iran", "israel",
    "russia", "ukraine", "middle east", "red sea",
]
SAFE_HAVEN = [
    "safe haven", "uncertainty", "risk off", "flight to safety",
    "market crash", "recession fear",
]

RELEVANCE_THRESHOLD = 0.1


class GoldRelevanceEngine:
    """Scores article relevance to gold (0.0 - 1.0)."""

    def score(self, article: Article) -> float:
        text = f"{article.title} {article.summary} {article.content}".lower()

        direct = sum(1 for signal in DIRECT_SIGNALS if signal in text)
        macro = sum(1 for signal in MACRO_SIGNALS if signal in text)
        geo = sum(1 for signal in GEO_SIGNALS if signal in text)
        haven = sum(1 for signal in SAFE_HAVEN if signal in text)

        total = 0.0
        total += min(direct * 0.25, 0.5)
        total += min(macro * 0.1, 0.3)
        total += min(geo * 0.1, 0.25)
        total += min(haven * 0.15, 0.2)

        if "gold" in article.title.lower():
            total += 0.15

        return min(1.0, round(total, 3))