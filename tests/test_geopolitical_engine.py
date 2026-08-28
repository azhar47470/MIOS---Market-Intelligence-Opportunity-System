from datetime import UTC, datetime, timedelta

from app.application.engines.geopolitical_engine import GeopoliticalIntelligenceEngine
from app.domain.market_data import DataProviderId, NewsArticle


def _article(title: str, summary: str = "") -> NewsArticle:
    return NewsArticle(
        article_id=title,
        title=title,
        url=f"https://example.com/{abs(hash(title))}",
        source_name="Example",
        published_at=datetime.now(UTC) - timedelta(hours=1),
        summary=summary,
        provider=DataProviderId.GDELT,
    )


def test_no_risk_signals_scores_the_neutral_baseline():
    engine = GeopoliticalIntelligenceEngine()
    result = engine.analyze((_article("Quarterly earnings season begins for major retailers"),))

    assert result.risk_score == 35


def test_high_risk_country_and_topic_coverage_scores_above_a_lone_risk_term(monkeypatch):
    # Task 5: this reuses the clusters/countries article_intelligence.py already computes
    # (previously only fed into evidence text, never into the risk score itself) instead of
    # re-scanning raw text with a second, separate 8-term list.
    engine = GeopoliticalIntelligenceEngine()
    generic = (_article("Regional shipping disruption reported near a major port"),)
    targeted = (
        _article(
            "Iran sanctions escalate as central bank warns of trade war fallout",
            "Analysts flag safe haven demand amid the conflict.",
        ),
    )

    generic_result = engine.analyze(generic)
    targeted_result = engine.analyze(targeted)

    assert targeted_result.risk_score > generic_result.risk_score
    description = targeted_result.evidence[0].description
    assert "Iran" in description
    assert "cluster(s) tagged" in description


def test_commodity_topic_is_detected_without_conflict_language():
    # A pure supply-chain/export event should still register as a geopolitical topic hit
    # even with none of the original 8 war/sanction-style risk terms present.
    engine = GeopoliticalIntelligenceEngine()
    result = engine.analyze(
        (
            _article(
                "Major exporter weighs export ban on rare mining output",
                "Supply chain concerns mount for industrial buyers.",
            ),
        )
    )

    assert result.risk_score > 35
    assert "cluster(s) tagged" in result.evidence[0].description
