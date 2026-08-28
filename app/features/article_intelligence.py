import hashlib
import re
from collections import defaultdict
from datetime import UTC, datetime

from app.domain.features import ArticleCluster, ArticleIntelligenceFeatureSet
from app.domain.market_data import NewsArticle

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_COUNTRIES = {
    "china",
    "india",
    "iran",
    "israel",
    "japan",
    "russia",
    "saudi arabia",
    "ukraine",
    "united states",
}
_INSTITUTIONS = {
    "bank of england",
    "ecb",
    "federal reserve",
    "fomc",
    "imf",
    "opec",
    "people's bank of china",
}
_TOPIC_TERMS = {
    "central_bank": (
        "central bank",
        "federal reserve",
        "fomc",
        "ecb",
        "boj",
        "pboc",
        "monetary policy",
        "rate decision",
    ),
    "conflict": ("war", "conflict", "attack", "missile", "invasion", "military"),
    "sanctions": ("sanction", "embargo", "trade ban", "asset freeze"),
    "inflation": ("inflation", "cpi", "ppi", "pce", "deflation"),
    "employment": ("employment", "payroll", "jobs", "nfp", "unemployment"),
    "interest_rates": ("interest rate", "rate cut", "rate hike", "yield", "fed funds"),
    "dollar": ("dollar", "usd", "dxy", "greenback", "dollar index"),
    "treasuries": ("treasury", "treasuries", "bond", "gilts", "sovereign debt"),
    "gdp": ("gdp", "gross domestic", "economic growth", "recession"),
    "gold": ("gold", "bullion", "xau", "precious metal", "gold price"),
    "safe_haven": ("safe haven", "risk aversion", "risk off", "flight to safety"),
    "commodity": ("export ban", "mining", "supply chain", "commodity", "oil"),
    "etf": ("etf", "exchange-traded", "spdr gold", "gld", "flows"),
    "politics": ("election", "president", "congress", "government", "policy"),
}

_RELEVANCE_SIGNALS = (
    "federal reserve",
    "interest rate",
    "inflation",
    "cpi",
    "dollar",
    "dxy",
    "treasury",
    "real yield",
    "monetary policy",
    "rate cut",
    "rate hike",
    "war",
    "sanctions",
    "geopolitical",
    "crisis",
    "conflict",
    "iran",
    "israel",
    "russia",
    "ukraine",
    "middle east",
    "safe haven",
    "uncertainty",
    "risk off",
    "flight to safety",
    "market crash",
    "recession fear",
)


def build_article_intelligence(
    articles: tuple[NewsArticle, ...],
    *,
    now: datetime | None = None,
) -> ArticleIntelligenceFeatureSet:
    """Create transparent article-level research features without assigning market direction."""
    reference_time = now or datetime.now(UTC)
    unique = _deduplicate(articles)
    clusters = _clusters(unique)
    all_text = " ".join(_article_text(article) for article in unique).lower()
    relevance = [_gold_relevance(article) for article in unique]
    return ArticleIntelligenceFeatureSet(
        source_article_count=len(articles),
        unique_article_count=len(unique),
        duplicate_article_count=max(0, len(articles) - len(unique)),
        clusters=clusters,
        entities=_entities(unique),
        countries=tuple(sorted(country.title() for country in _COUNTRIES if country in all_text)),
        institutions=tuple(
            sorted(institution.title() for institution in _INSTITUTIONS if institution in all_text)
        ),
        average_gold_relevance=round(sum(relevance) / len(relevance)) if relevance else 0,
        estimated_duration_hours=_estimated_duration_hours(unique, clusters, reference_time),
        high_relevance_article_count=sum(1 for item in relevance if item >= 70),
    )


def _deduplicate(articles: tuple[NewsArticle, ...]) -> tuple[NewsArticle, ...]:
    unique: dict[str, NewsArticle] = {}
    for article in sorted(articles, key=lambda item: item.published_at, reverse=True):
        unique.setdefault(_fingerprint(article), article)
    return tuple(unique.values())


def _clusters(articles: tuple[NewsArticle, ...]) -> tuple[ArticleCluster, ...]:
    groups: dict[str, list[NewsArticle]] = defaultdict(list)
    for article in articles:
        tokens = _tokens(article.title)
        key = " ".join(sorted(tokens)[:3]) or "uncategorized"
        groups[key].append(article)
    return tuple(
        ArticleCluster(
            cluster_id=hashlib.sha256(key.encode()).hexdigest()[:16],
            narrative=key,
            article_count=len(group),
            representative_headline=group[0].title,
            topics=_topics(group),
        )
        for key, group in sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)[:8]
    )


def _topics(articles: list[NewsArticle]) -> tuple[str, ...]:
    text = " ".join(_article_text(article) for article in articles).lower()
    return tuple(
        topic for topic, terms in _TOPIC_TERMS.items() if any(term in text for term in terms)
    )


def _gold_relevance(article: NewsArticle) -> int:
    text = _article_text(article).lower()
    if "xau/usd" in text or "gold price" in text:
        return 95
    if "gold" in text:
        return 80
    if any(signal in text for signal in _RELEVANCE_SIGNALS):
        return 55
    return 25


def _estimated_duration_hours(
    articles: tuple[NewsArticle, ...], clusters: tuple[ArticleCluster, ...], now: datetime
) -> int:
    if not articles:
        return 0
    latest_published_at = max(article.published_at for article in articles)
    age_hours = max(0, int((now - latest_published_at).total_seconds() / 3600))
    cluster_bonus = min(72, sum(cluster.article_count for cluster in clusters) * 6)
    topic_bonus = min(72, sum(len(cluster.topics) for cluster in clusters) * 6)
    return min(720, max(6, 24 + cluster_bonus + topic_bonus - age_hours))


def _entities(articles: tuple[NewsArticle, ...]) -> tuple[str, ...]:
    entities: set[str] = set()
    for article in articles:
        entities.update(re.findall(r"\b(?:[A-Z][a-z]+\s){0,2}[A-Z][a-z]+\b", article.title))
    return tuple(sorted(entities))[:20]


def _fingerprint(article: NewsArticle) -> str:
    normalized_url = article.url.lower().split("?")[0].rstrip("/")
    normalized_title = " ".join(_tokens(article.title))
    return hashlib.sha256(f"{normalized_url}|{normalized_title}".encode()).hexdigest()


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in _STOP_WORDS]


def _article_text(article: NewsArticle) -> str:
    return f"{article.title} {article.summary or ''}"
