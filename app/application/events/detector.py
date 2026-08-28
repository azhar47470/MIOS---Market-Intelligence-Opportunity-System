"""Event detection — merge cross-source coverage of the same story into one event.

Port of the mios_v2 Stage 8 detector onto the GIP domain. Articles are clustered on
title-token overlap (Jaccard similarity or >=3 shared significant tokens), so the same
story from different outlets becomes a single event with multiple sources for
cross-source verification to confirm against. Falls back to one-event-per-article so
the pipeline never crashes on bad input.
"""

from hashlib import md5
import logging

from app.domain.intelligence import MarketEvent, MarketEventType
from app.domain.market_data import NewsArticle

logger = logging.getLogger("mios.events")

_STOPWORDS = frozenset(
    {
        "the", "and", "for", "are", "but", "not", "you", "your", "our", "we", "they",
        "this", "that", "these", "those", "with", "from", "into", "over", "after",
        "amid", "against", "about", "than", "then", "will", "would", "could", "should",
        "may", "might", "can", "has", "have", "had", "was", "were", "been", "being",
        "says", "said", "say", "report", "reports", "update", "updates", "latest",
        "live", "breaking", "news", "just", "also", "more", "most", "some", "any",
        "what", "when", "where", "who", "why", "how", "which", "their", "there",
        "here", "out", "off", "down", "all", "new", "now", "one", "two", "per", "via",
        "gold", "silver", "us", "u", "s", "dollar", "price", "ounces", "xau",
    }
)


class EventDetector:
    def __init__(self, jaccard_threshold: float = 0.45, max_cluster: int = 30) -> None:
        self._jaccard_threshold = jaccard_threshold
        self._max_cluster = max_cluster

    def detect(self, articles: tuple[NewsArticle, ...]) -> tuple[MarketEvent, ...]:
        if not articles:
            return ()
        try:
            return self._detect(articles)
        except Exception as error:  # pragma: no cover - defensive only
            logger.error("EventDetector failed (%s); one-event-per-article fallback", error)
            return tuple(_singleton(article) for article in articles)

    def _detect(self, articles: tuple[NewsArticle, ...]) -> tuple[MarketEvent, ...]:
        n = len(articles)
        token_sets = tuple(_tokens(article.title) for article in articles)
        parent = list(range(n))
        sizes = [1] * n

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            root_a, root_b = find(a), find(b)
            if root_a == root_b:
                return
            if sizes[root_a] < sizes[root_b]:
                root_a, root_b = root_b, root_a
            parent[root_b] = root_a
            sizes[root_a] += sizes[root_b]

        for i in range(n):
            for j in range(i + 1, n):
                root_i, root_j = find(i), find(j)
                if root_i == root_j:
                    continue
                if max(sizes[root_i], sizes[root_j]) >= self._max_cluster:
                    continue
                shared = token_sets[i] & token_sets[j]
                if not shared:
                    continue
                if _jaccard(token_sets[i], token_sets[j]) >= self._jaccard_threshold:
                    union(i, j)
                elif len(shared) >= 3:
                    union(i, j)

        groups: dict[int, list[int]] = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)

        events = [
            _build_event(tuple(articles[index] for index in member_indices))
            for member_indices in groups.values()
        ]
        events.sort(key=lambda event: event.confidence, reverse=True)
        logger.info("EventDetector: %d articles -> %d events", n, len(events))
        return tuple(events)


def _tokens(title: str) -> set[str]:
    tokens: set[str] = set()
    for raw in (title or "").lower().split():
        token = "".join(character for character in raw if character.isalnum())
        if len(token) >= 3 and token not in _STOPWORDS:
            tokens.add(token)
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _singleton(article: NewsArticle) -> MarketEvent:
    return MarketEvent(
        event_id=_event_id(article.article_id, (article.source_name,)),
        title=article.title,
        summary=article.summary or "",
        sources=(article.source_name,),
        article_ids=(article.article_id,),
        confidence=0.3,
        first_seen=article.published_at,
        last_seen=article.published_at,
    )


def _build_event(cluster: tuple[NewsArticle, ...]) -> MarketEvent:
    representative = max(
        cluster, key=lambda article: len(article.summary or "")
    )
    sources = tuple(sorted({article.source_name for article in cluster}))
    size = len(cluster)
    source_count = len(sources)
    confidence = 0.30 + 0.08 * min(size, 5) + 0.12 * min(source_count, 4)
    published = [article.published_at for article in cluster if article.published_at]
    return MarketEvent(
        event_id=_event_id(representative.article_id, sources),
        title=representative.title,
        summary=representative.summary or "",
        article_ids=tuple(article.article_id for article in cluster),
        sources=sources,
        confidence=min(0.95, confidence),
        first_seen=min(published) if published else None,
        last_seen=max(published) if published else None,
    )


def _event_id(seed: str, sources: tuple[str, ...]) -> str:
    digest = md5(f"{seed}|{','.join(sources)}".encode("utf-8")).hexdigest()
    return f"EVT-{digest[:20]}"
