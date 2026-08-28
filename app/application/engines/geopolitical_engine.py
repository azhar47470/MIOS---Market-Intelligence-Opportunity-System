from datetime import UTC, datetime, timedelta

from app.application.engines.news_engine import _article_feature_evidence
from app.domain.ai import AIContext, AIGoldImpactDirection, AnalystReport
from app.domain.common import (
    ConfidenceScore,
    ContractStatus,
    EvidenceRecord,
    EvidenceStrength,
    RiskRecord,
)
from app.domain.features import ArticleIntelligenceFeatureSet
from app.domain.intelligence import DirectionalBias, EngineId, GeopoliticalAnalysis
from app.domain.market_data import NewsArticle
from app.features.article_intelligence import build_article_intelligence


class GeopoliticalIntelligenceEngine:
    _RISK_TERMS = (
        "war",
        "sanction",
        "missile",
        "attack",
        "conflict",
        "invasion",
        "shipping",
        "escalation",
    )
    # Topics from the shared article-intelligence pipeline that carry geopolitical-risk
    # weight (Task 5): reuses the clustering/entity-extraction work already done in
    # `build_article_intelligence` instead of re-scanning raw text with a second, separate
    # term list. "commodity" catches export-ban/mining/supply-chain events specifically,
    # since those move gold without necessarily reading as "conflict" or "sanctions".
    _GEOPOLITICAL_TOPICS = frozenset(
        {"conflict", "sanctions", "safe_haven", "central_bank", "commodity"}
    )
    # Countries most associated with the conflict/sanctions coverage that actually moves
    # gold as a safe-haven asset. Deliberately narrower than article_intelligence's full
    # country list (which also matches routine-news countries like Japan or India) — this
    # is a risk signal, not a general geography tag.
    _HIGH_RISK_COUNTRIES = frozenset({"Iran", "Israel", "Russia", "Ukraine"})

    def __init__(self, ai_agent=None, ai_reasoning_enabled: bool = False) -> None:
        self._ai_agent = ai_agent
        self._ai_reasoning_enabled = ai_reasoning_enabled

    def analyze(
        self,
        articles: tuple[NewsArticle, ...],
        analyst_report: AnalystReport | None = None,
    ) -> GeopoliticalAnalysis:
        started_at = datetime.now(UTC)
        fresh_articles = tuple(
            article
            for article in articles
            if article.published_at >= datetime.now(UTC) - timedelta(hours=48)
        )
        features = build_article_intelligence(fresh_articles)
        fallback_reason = None
        if analyst_report is not None and analyst_report.provider != "deterministic_fallback":
            risk_score, confidence, bias, evidence = _analysis_from_specialist_report(
                analyst_report
            )
        elif self._ai_reasoning_enabled and self._ai_agent is not None and fresh_articles:
            try:
                assessment, _raw_json, provider = self._ai_agent.analyze_impact(
                    _context_from_articles(
                        fresh_articles,
                        "Assess geopolitical risk and safe-haven demand for gold.",
                    )
                )
                risk_score = max(0, min(100, assessment.severity))
                confidence = max(15, min(90, assessment.reliability))
                bias = _bias_from_ai_direction(assessment.gold_impact_direction, risk_score)
                evidence = (
                    EvidenceRecord(
                        evidence_id="GEO-AI-001",
                        category="AI Geopolitical Risk",
                        description=(
                            f"{assessment.gold_impact_direction.value} gold impact "
                            f"({assessment.gold_impact_magnitude}/100): "
                            f"{assessment.reasoning}"
                        )[:500],
                        strength=(
                            EvidenceStrength.HIGH if risk_score >= 70 else EvidenceStrength.MEDIUM
                        ),
                        confidence=confidence,
                        source=f"Geopolitical Intelligence Engine ({provider})",
                    ),
                )
            except Exception as error:
                fallback_reason = str(error)
                risk_score, confidence, bias, evidence = self._keyword_fallback(
                    fresh_articles, fallback_reason, features
                )
        else:
            fallback_reason = "AI reasoning disabled or unavailable." if fresh_articles else None
            risk_score, confidence, bias, evidence = self._keyword_fallback(
                fresh_articles, fallback_reason, features
            )

        evidence = (*evidence, *_article_feature_evidence(features, confidence))[:10]
        risks: tuple[RiskRecord, ...] = ()
        if risk_score >= 75:
            risks = (
                RiskRecord(
                    risk=(
                        "Fast-moving geopolitical situation may cause gap risk "
                        "and volatile spreads."
                    ),
                    severity=EvidenceStrength.HIGH,
                    probability=75,
                ),
            )
        elif fallback_reason is not None:
            risks = (
                RiskRecord(
                    risk=(
                        "AI geopolitical analysis unavailable; keyword fallback used. "
                        f"{fallback_reason}"
                    ),
                    severity=EvidenceStrength.MEDIUM,
                    probability=55,
                ),
            )
        return GeopoliticalAnalysis(
            engine=EngineId.GEOPOLITICAL,
            status=ContractStatus.SUCCESS if fresh_articles else ContractStatus.NO_DATA,
            confidence=ConfidenceScore(
                value=confidence, reason="Geopolitical confidence reflects fresh global coverage."
            ),
            quality=confidence,
            score=risk_score,
            bias=bias,
            evidence=evidence,
            risks=risks,
            execution_ms=_elapsed_ms(started_at),
            risk_score=risk_score,
            conflict_status="Elevated" if risk_score >= 70 else "Contained",
            expected_market_impact=bias,
        )

    def _risk_hits(self, articles: tuple[NewsArticle, ...]) -> int:
        count = 0
        for article in articles:
            text = f"{article.title} {article.summary or ''}".lower()
            count += sum(1 for term in self._RISK_TERMS if term in text)
        return count

    def _keyword_fallback(
        self,
        articles: tuple[NewsArticle, ...],
        reason: str | None,
        features: ArticleIntelligenceFeatureSet,
    ) -> tuple[int, int, DirectionalBias, tuple[EvidenceRecord, ...]]:
        risk_hits = self._risk_hits(articles)
        topic_hits = sum(
            1
            for cluster in features.clusters
            for topic in cluster.topics
            if topic in self._GEOPOLITICAL_TOPICS
        )
        flagged_countries = tuple(
            country for country in features.countries if country in self._HIGH_RISK_COUNTRIES
        )
        risk_score = max(
            0,
            min(100, 35 + risk_hits * 10 + topic_hits * 6 + len(flagged_countries) * 8),
        )
        confidence = min(35 if reason else 80, 30 + len(articles) * 5)
        bias = DirectionalBias.BULLISH if risk_score >= 60 else DirectionalBias.NEUTRAL
        description = f"Detected {risk_hits} geopolitical risk cue(s) in fresh global articles."
        if topic_hits:
            description += (
                f" {topic_hits} article cluster(s) tagged for conflict, sanctions, "
                "safe-haven, central-bank, or commodity-supply themes."
            )
        if flagged_countries:
            description += f" Coverage centers on {', '.join(flagged_countries)}."
        if reason:
            description = f"{description} AI fallback reason: {reason}"
        evidence = (
            EvidenceRecord(
                evidence_id="GEO-FALLBACK-001" if reason else "GEO-RISK-001",
                category="Geopolitical Risk",
                description=description,
                strength=EvidenceStrength.LOW if reason else EvidenceStrength.MEDIUM,
                confidence=confidence,
                source="Geopolitical Intelligence Engine",
            ),
        )
        return risk_score, confidence, bias, evidence


def _analysis_from_specialist_report(
    report: AnalystReport,
) -> tuple[int, int, DirectionalBias, tuple[EvidenceRecord, ...]]:
    direction_values = {
        AIGoldImpactDirection.BULLISH: 1,
        AIGoldImpactDirection.BEARISH: -1,
        AIGoldImpactDirection.NEUTRAL: 0,
        AIGoldImpactDirection.MIXED: 0,
    }
    weighted_direction = sum(
        direction_values[item.direction] * item.confidence for item in report.structured_evidence
    )
    total_weight = sum(item.confidence for item in report.structured_evidence)
    average_direction = weighted_direction / total_weight if total_weight else 0
    risk_score = max(0, min(100, 45 + round(abs(average_direction) * 35)))
    if average_direction > 0:
        bias = DirectionalBias.BULLISH
    elif average_direction < 0:
        bias = DirectionalBias.BEARISH
    else:
        bias = DirectionalBias.MIXED
    evidence = [
        EvidenceRecord(
            evidence_id=f"GEO-REPORT-{report.report_id[-80:]}",
            category="AI Geopolitical Research",
            description=report.summary[:500],
            strength=EvidenceStrength.HIGH if report.confidence >= 70 else EvidenceStrength.MEDIUM,
            confidence=report.confidence,
            source="Geopolitical Intelligence Engine (AI Research Desk)",
        )
    ]
    evidence.extend(
        EvidenceRecord(
            evidence_id=f"GEO-AI-{index + 1}",
            category=item.category,
            description=item.claim,
            strength=item.strength,
            confidence=item.confidence,
            source="Geopolitical Intelligence Engine (AI Research Desk)",
        )
        for index, item in enumerate(report.structured_evidence[:6])
    )
    return risk_score, report.confidence, bias, tuple(evidence)


def _context_from_articles(articles: tuple[NewsArticle, ...], objective: str) -> AIContext:
    return AIContext(
        context_id=f"geopolitical-{datetime.now(UTC).isoformat()}",
        objective=objective,
        facts={
            "articles": [
                {
                    "title": article.title,
                    "summary": article.summary,
                    "source": article.source_name,
                    "published_at": article.published_at.isoformat(),
                    "url": article.url,
                }
                for article in articles[:10]
            ]
        },
    )


def _bias_from_ai_direction(direction: AIGoldImpactDirection, risk_score: int) -> DirectionalBias:
    if direction == AIGoldImpactDirection.BULLISH and risk_score >= 50:
        return DirectionalBias.BULLISH
    if direction == AIGoldImpactDirection.BEARISH:
        return DirectionalBias.BEARISH
    if direction == AIGoldImpactDirection.MIXED:
        return DirectionalBias.MIXED
    return DirectionalBias.NEUTRAL


def _elapsed_ms(started_at: datetime) -> int:
    return int((datetime.now(UTC) - started_at).total_seconds() * 1000)
