"""Event narrative pipeline — events (Stage 8) -> narratives (Stage 9) -> verification
(Stage 10), the mios_v2 ordering: narratives are built from pre-verification event
confidence, then the verifier confirms events and applies source-tier bonuses.
"""

from app.application.events.clusterer import NarrativeClusterer
from app.application.events.detector import EventDetector
from app.application.events.verifier import CrossSourceVerifier
from app.domain.intelligence import MarketEvent, MarketNarrative
from app.domain.market_data import NewsArticle


class EventNarrativePipeline:
    def __init__(
        self,
        detector: EventDetector | None = None,
        clusterer: NarrativeClusterer | None = None,
        verifier: CrossSourceVerifier | None = None,
    ) -> None:
        self._detector = detector or EventDetector()
        self._clusterer = clusterer or NarrativeClusterer()
        self._verifier = verifier or CrossSourceVerifier()

    def run(
        self, articles: tuple[NewsArticle, ...]
    ) -> tuple[tuple[MarketEvent, ...], tuple[MarketNarrative, ...]]:
        events = self._detector.detect(articles)
        narratives = self._clusterer.cluster(events, articles)
        events = self._verifier.verify(events)
        return events, narratives
