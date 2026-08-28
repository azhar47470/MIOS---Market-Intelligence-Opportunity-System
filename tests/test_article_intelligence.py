from datetime import UTC, datetime

from app.application.engines.geopolitical_engine import GeopoliticalIntelligenceEngine
from app.application.engines.news_engine import NewsIntelligenceEngine
from app.domain.ai import (
    AgentRole,
    AIGoldImpactDirection,
    AnalystEvidence,
    AnalystReport,
)
from app.domain.common import EvidenceStrength
from app.domain.enums import Recommendation
from app.domain.market_data import DataProviderId, NewsArticle
from app.features.article_intelligence import build_article_intelligence


def test_article_intelligence_deduplicates_clusters_and_extracts_context():
    articles = (
        _article("Gold gains as Federal Reserve policy outlook shifts", "https://example.test/a"),
        _article("Gold gains as Federal Reserve policy outlook shifts", "https://example.test/a?ref=x"),
        _article("Iran conflict raises safe-haven demand for gold", "https://example.test/b"),
    )

    features = build_article_intelligence(articles, now=datetime(2026, 7, 14, tzinfo=UTC))

    assert features.source_article_count == 3
    assert features.unique_article_count == 2
    assert features.duplicate_article_count == 1
    assert features.clusters
    assert "Iran" in features.entities
    assert "Federal Reserve" in features.institutions
    assert features.average_gold_relevance >= 80
    assert features.estimated_duration_hours > 0


def test_news_and_geopolitical_engines_consume_validated_specialist_reports():
    report = _analyst_report()
    articles = (_article("Iran conflict raises safe-haven demand for gold", "https://example.test/b"),)

    news = NewsIntelligenceEngine().analyze(articles, report)
    geo = GeopoliticalIntelligenceEngine().analyze(articles, report)

    assert news.evidence[0].category == "AI News Research"
    assert "Article Deduplication" in {item.category for item in news.evidence}
    assert geo.evidence[0].category == "AI Geopolitical Research"
    assert "Narrative Detection" in {item.category for item in geo.evidence}


def _article(title: str, url: str) -> NewsArticle:
    return NewsArticle(
        article_id=url,
        title=title,
        url=url,
        source_name="Example",
        published_at=datetime.now(UTC),
        summary="Federal Reserve and Iran developments are under review.",
        provider=DataProviderId.NEWSAPI,
    )


def _analyst_report() -> AnalystReport:
    return AnalystReport(
        report_id="AI-NEWS-REPORT",
        role=AgentRole.NEWS_ANALYST,
        context_id="news-context",
        provider="groq",
        summary="Conflict and policy narratives support safe-haven demand, with event risk.",
        bullish_arguments=("Safe-haven demand is visible.",),
        bearish_arguments=("A de-escalation would reverse demand.",),
        confidence=72,
        risks=("Headlines can reverse quickly.",),
        recommendation=Recommendation.HOLD,
        structured_evidence=(
            AnalystEvidence(
                evidence_id="news-1",
                category="Safe Haven",
                claim="The supplied conflict narrative can support gold demand.",
                direction=AIGoldImpactDirection.BULLISH,
                strength=EvidenceStrength.HIGH,
                confidence=72,
                source_fact_keys=("articles",),
            ),
        ),
        missing_evidence=("Cross-asset confirmation is unavailable.",),
        required_confirmations=("Confirm sustained safe-haven flows.",),
    )
