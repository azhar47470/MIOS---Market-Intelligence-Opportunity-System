from datetime import UTC, datetime, timedelta

from app.domain.ai import AIContext, AIGoldImpactDirection, AINewsImpactAssessment, AnalystReport
from app.domain.common import (
    ConfidenceScore,
    ContractStatus,
    EvidenceRecord,
    EvidenceStrength,
    RiskRecord,
)
from app.domain.intelligence import DirectionalBias, EngineId, NewsAnalysis
from app.domain.market_data import NewsArticle
from app.features.article_intelligence import build_article_intelligence


class NewsIntelligenceEngine:
    _BULLISH_TERMS = ("rate cut", "dovish", "safe haven", "inflation fear", "crisis", "war")
    _BEARISH_TERMS = ("rate hike", "hawkish", "strong dollar", "risk rally", "ceasefire")

    def __init__(self, ai_agent=None, ai_reasoning_enabled: bool = False) -> None:
        self._ai_agent = ai_agent
        self._ai_reasoning_enabled = ai_reasoning_enabled

    def analyze(
        self,
        articles: tuple[NewsArticle, ...],
        analyst_report: AnalystReport | None = None,
    ) -> NewsAnalysis:
        started_at = datetime.now(UTC)
        fresh_articles = self._fresh_articles(articles)
        features = build_article_intelligence(fresh_articles)
        fallback_reason = None
        if analyst_report is not None and analyst_report.provider != "deterministic_fallback":
            score, confidence, evidence, high_severity = _analysis_from_specialist_report(
                analyst_report,
                category="AI News Research",
                source="News Intelligence Engine (AI Research Desk)",
            )
        elif self._ai_reasoning_enabled and self._ai_agent is not None and fresh_articles:
            try:
                assessment, _raw_json, provider = self._ai_agent.analyze_impact(
                    _context_from_articles(fresh_articles, "Assess professional gold news.")
                )
                score, confidence, evidence, high_severity = _analysis_from_ai_assessment(
                    assessment,
                    evidence_id="NEWS-AI-001",
                    category="AI News Reasoning",
                    source=f"News Intelligence Engine ({provider})",
                )
            except Exception as error:
                fallback_reason = str(error)
                score, confidence, evidence, high_severity = self._keyword_fallback(
                    fresh_articles, fallback_reason
                )
        else:
            disabled_reason = "AI reasoning disabled or unavailable."
            fallback_reason = disabled_reason if fresh_articles else None
            score, confidence, evidence, high_severity = self._keyword_fallback(
                fresh_articles, fallback_reason
            )

        evidence = (*evidence, *_article_feature_evidence(features, confidence))[:10]
        risks: tuple[RiskRecord, ...] = ()
        if not fresh_articles:
            risks = (
                RiskRecord(
                    risk="No fresh professional news was available for analysis.",
                    severity=EvidenceStrength.MEDIUM,
                    probability=60,
                ),
            )
        elif fallback_reason is not None:
            risks = (
                RiskRecord(
                    risk=f"AI news analysis unavailable; keyword fallback used. {fallback_reason}",
                    severity=EvidenceStrength.MEDIUM,
                    probability=55,
                ),
            )
        return NewsAnalysis(
            engine=EngineId.NEWS,
            status=ContractStatus.SUCCESS if fresh_articles else ContractStatus.NO_DATA,
            confidence=ConfidenceScore(
                value=confidence,
                reason="News confidence reflects article freshness and signal density.",
            ),
            quality=confidence,
            score=score,
            bias=_bias_from_score(score),
            evidence=evidence,
            risks=risks,
            execution_ms=_elapsed_ms(started_at),
            analyzed_articles=len(fresh_articles),
            high_severity_events=high_severity,
        )

    def _fresh_articles(self, articles: tuple[NewsArticle, ...]) -> tuple[NewsArticle, ...]:
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        return tuple(article for article in articles if article.published_at >= cutoff)

    def _count_terms(self, articles: tuple[NewsArticle, ...], terms: tuple[str, ...]) -> int:
        count = 0
        for article in articles:
            text = f"{article.title} {article.summary or ''}".lower()
            count += sum(1 for term in terms if term in text)
        return count

    def _keyword_fallback(
        self, articles: tuple[NewsArticle, ...], reason: str | None
    ) -> tuple[int, int, tuple[EvidenceRecord, ...], int]:
        bullish_hits = self._count_terms(articles, self._BULLISH_TERMS)
        bearish_hits = self._count_terms(articles, self._BEARISH_TERMS)
        score = max(0, min(100, 50 + (bullish_hits * 6) - (bearish_hits * 6)))
        confidence = min(35 if reason else 80, 35 + len(articles) * 5)
        high_severity = min(10, bullish_hits + bearish_hits)
        description = (
            f"Detected {bullish_hits} supportive and {bearish_hits} adverse gold news cue(s)."
        )
        if reason:
            description = f"{description} AI fallback reason: {reason}"
        return (
            score,
            confidence,
            (
                EvidenceRecord(
                    evidence_id="NEWS-FALLBACK-001" if reason else "NEWS-TONE-001",
                    category="News Tone",
                    description=description,
                    strength=EvidenceStrength.LOW if reason else EvidenceStrength.MEDIUM,
                    confidence=confidence,
                    source="News Intelligence Engine",
                ),
            ),
            high_severity,
        )


def _context_from_articles(articles: tuple[NewsArticle, ...], objective: str) -> AIContext:
    return AIContext(
        context_id=f"news-{datetime.now(UTC).isoformat()}",
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


def _analysis_from_ai_assessment(
    assessment: AINewsImpactAssessment,
    *,
    evidence_id: str,
    category: str,
    source: str,
) -> tuple[int, int, tuple[EvidenceRecord, ...], int]:
    direction_multiplier = {
        AIGoldImpactDirection.BULLISH: 1,
        AIGoldImpactDirection.BEARISH: -1,
        AIGoldImpactDirection.NEUTRAL: 0,
        AIGoldImpactDirection.MIXED: 0,
    }[assessment.gold_impact_direction]
    score = max(
        0,
        min(100, 50 + int(direction_multiplier * assessment.gold_impact_magnitude * 0.4)),
    )
    confidence = max(15, min(90, assessment.reliability))
    severity = assessment.severity
    return (
        score,
        confidence,
        (
            EvidenceRecord(
                evidence_id=evidence_id,
                category=category,
                description=(
                    f"{assessment.gold_impact_direction.value} gold impact "
                    f"({assessment.gold_impact_magnitude}/100): {assessment.reasoning}"
                )[:500],
                strength=_strength_from_severity(severity),
                confidence=confidence,
                source=source,
            ),
        ),
        1 if severity >= 70 else 0,
    )


def _analysis_from_specialist_report(
    report: AnalystReport,
    *,
    category: str,
    source: str,
) -> tuple[int, int, tuple[EvidenceRecord, ...], int]:
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
    score = (
        50
        if not total_weight
        else max(0, min(100, 50 + round(weighted_direction / total_weight * 35)))
    )
    evidence = [
        EvidenceRecord(
            evidence_id=f"NEWS-REPORT-{report.report_id[-80:]}",
            category=category,
            description=report.summary[:500],
            strength=EvidenceStrength.HIGH if report.confidence >= 70 else EvidenceStrength.MEDIUM,
            confidence=report.confidence,
            source=source,
        )
    ]
    evidence.extend(
        EvidenceRecord(
            evidence_id=f"NEWS-AI-{index + 1}",
            category=item.category,
            description=item.claim,
            strength=item.strength,
            confidence=item.confidence,
            source=source,
        )
        for index, item in enumerate(report.structured_evidence[:6])
    )
    high_severity = sum(
        1 for item in report.structured_evidence if item.strength == EvidenceStrength.CRITICAL
    )
    return score, report.confidence, tuple(evidence), high_severity


def _article_feature_evidence(features, confidence: int) -> tuple[EvidenceRecord, ...]:
    evidence: list[EvidenceRecord] = []
    if features.source_article_count:
        evidence.append(
            EvidenceRecord(
                evidence_id="NEWS-DEDUP-001",
                category="Article Deduplication",
                description=(
                    f"{features.unique_article_count} unique article(s) retained; "
                    f"{features.duplicate_article_count} duplicate(s) removed."
                ),
                strength=EvidenceStrength.MEDIUM,
                confidence=max(35, confidence - 8),
                source="News Intelligence Engine",
            )
        )
    if features.clusters:
        narratives = ", ".join(cluster.narrative for cluster in features.clusters[:3])
        evidence.append(
            EvidenceRecord(
                evidence_id="NEWS-NARRATIVE-001",
                category="Narrative Detection",
                description=(
                    f"{len(features.clusters)} narrative cluster(s); leading themes: {narratives}."
                ),
                strength=EvidenceStrength.MEDIUM,
                confidence=max(35, confidence - 10),
                source="News Intelligence Engine",
            )
        )
    if features.entities or features.countries or features.institutions:
        labels = ", ".join(
            (*features.entities[:4], *features.countries[:3], *features.institutions[:3])
        )
        evidence.append(
            EvidenceRecord(
                evidence_id="NEWS-ENTITIES-001",
                category="Entity Extraction",
                description=f"Extracted entities and institutions: {labels}.",
                strength=EvidenceStrength.LOW,
                confidence=max(30, confidence - 15),
                source="News Intelligence Engine",
            )
        )
    if features.unique_article_count:
        evidence.append(
            EvidenceRecord(
                evidence_id="NEWS-RELEVANCE-001",
                category="Gold Relevance / Duration",
                description=(
                    f"Average gold relevance is {features.average_gold_relevance}/100; "
                    f"estimated narrative duration is {features.estimated_duration_hours} hour(s)."
                ),
                strength=EvidenceStrength.MEDIUM,
                confidence=max(35, confidence - 10),
                source="News Intelligence Engine",
            )
        )
    return tuple(evidence)


def _strength_from_severity(severity: int) -> EvidenceStrength:
    if severity >= 80:
        return EvidenceStrength.HIGH
    if severity >= 45:
        return EvidenceStrength.MEDIUM
    return EvidenceStrength.LOW


def _bias_from_score(score: int) -> DirectionalBias:
    if score >= 60:
        return DirectionalBias.BULLISH
    if score <= 40:
        return DirectionalBias.BEARISH
    return DirectionalBias.NEUTRAL


def _elapsed_ms(started_at: datetime) -> int:
    return int((datetime.now(UTC) - started_at).total_seconds() * 1000)
