"""Topic Classification — v2 Stage 6. Multi-label deterministic keyword matching."""

from __future__ import annotations

from app.infrastructure.news.article import Article

TOPIC_KEYWORDS = {
    "central_bank": ["federal reserve", "fed", "ecb", "boj", "pboc", "central bank", "fomc", "monetary policy", "rate decision"],
    "inflation": ["inflation", "cpi", "ppi", "consumer price", "producer price", "deflation", "stagflation"],
    "interest_rates": ["interest rate", "rate cut", "rate hike", "yield", "basis point", "fed funds"],
    "gold": ["gold", "bullion", "xau", "precious metal", "gold price", "gold etf"],
    "silver": ["silver", "xag"],
    "oil": ["oil", "brent", "wti", "crude", "opec", "petroleum"],
    "dollar": ["dollar", "usd", "dxy", "greenback", "dollar index"],
    "treasuries": ["treasury", "treasuries", "bond", "gilts", "sovereign debt", "bond auction"],
    "employment": ["employment", "jobs", "nonfarm", "nfp", "unemployment", "payroll", "labor market"],
    "gdp": ["gdp", "gross domestic", "economic growth", "recession", "expansion"],
    "war": ["war", "military", "attack", "strike", "missile", "invasion", "conflict"],
    "sanctions": ["sanctions", "embargo", "trade ban", "asset freeze"],
    "trade": ["trade", "tariff", "import", "export", "trade war", "trade deal"],
    "politics": ["election", "president", "congress", "parliament", "government", "policy"],
    "etf": ["etf", "exchange-traded", "spdr gold", "gld", "flows"],
    "cot": ["cot", "commitments of traders", "positioning", "speculative"],
    "mining": ["mining", "mine", "extraction", "production", "refinery"],
    "supply_chain": ["supply chain", "logistics", "shipping", "freight", "port"],
    "natural_disaster": ["earthquake", "flood", "hurricane", "disaster", "tsunami"],
    "crypto": ["bitcoin", "crypto", "digital currency", "cbdc"],
}


class TopicClassifier:
    """Multi-label topic classifier using keyword matching."""

    def classify(self, article: Article) -> tuple[str, ...]:
        text = f"{article.title} {article.summary} {article.content}".lower()
        matched: list[tuple[str, float]] = []
        for topic, keywords in TOPIC_KEYWORDS.items():
            hits = [keyword for keyword in keywords if keyword in text]
            if hits:
                matched.append((topic, round(min(1.0, len(hits) * 0.3), 2)))
        matched.sort(key=lambda item: item[1], reverse=True)
        return tuple(topic for topic, _ in matched)