from datetime import UTC, datetime
from decimal import Decimal
import uuid

from app.application.decision_config import DecisionEngineConfig
from app.domain.common import ContractStatus, EvidenceRecord, EvidenceStrength, RiskRecord
from app.domain.enums import NotificationPriority, Recommendation
from app.domain.intelligence import (
    AnalysisBundle,
    ConfidenceAttribution,
    DecisionContext,
    DecisionReport,
    DecisionTrace,
    DirectionalBias,
    EngineId,
    InvestmentScore,
    MarketRegime,
    OpportunityAssessment,
)
from app.domain.notification_models import ExpectedMove, InvalidationCondition


class OpportunityFilter:
    def __init__(self, config: DecisionEngineConfig) -> None:
        self._config = config

    def assess(
        self,
        analysis: AnalysisBundle,
    ) -> OpportunityAssessment:
        thresholds = self._config.thresholds
        technical = analysis.technical
        confidence = _aggregate_analysis_confidence(analysis)
        expected_move = technical.expected_move_usd or Decimal("0")
        high_risks = _high_risk_count(analysis)
        blockers: list[RiskRecord] = []
        if confidence < thresholds.minimum_confidence_for_action:
            blockers.append(
                RiskRecord(
                    risk=f"Aggregate confidence {confidence}% is below action threshold.",
                    severity=EvidenceStrength.HIGH,
                    probability=90,
                )
            )
        if high_risks > thresholds.max_high_severity_risks_for_action:
            blockers.append(
                RiskRecord(
                    risk="Too many high-severity risks are active for a disciplined action.",
                    severity=EvidenceStrength.HIGH,
                    probability=80,
                )
            )
        opportunity_score = max(
            0,
            min(
                100,
                round(
                    (
                        analysis.technical.score
                        + analysis.fundamental.score
                        + analysis.institutional.score
                        + analysis.regime.score
                    )
                    / 4
                )
                - (len(blockers) * 15),
            ),
        )
        if blockers:
            return OpportunityAssessment(
                passed=False,
                opportunity_score=opportunity_score,
                reason="Opportunity rejected by discipline filter; WAIT is preferred.",
                blocking_risks=tuple(blockers),
            )
        return OpportunityAssessment(
            passed=True,
            opportunity_score=opportunity_score,
            reason="Opportunity passes minimum evidence and risk filters.",
            required_action=Recommendation.BUY,
        )


class InvestmentScoringEngine:
    def score(self, analysis: AnalysisBundle) -> InvestmentScore:
        weighted_components: dict[EngineId, Decimal] = {}
        total = Decimal("0")
        values = {
            EngineId.TECHNICAL: analysis.technical.score,
            EngineId.FUNDAMENTAL: analysis.fundamental.score,
            EngineId.MARKET_REGIME: analysis.regime.score,
            EngineId.INSTITUTIONAL: analysis.institutional.score,
            EngineId.GEOPOLITICAL: analysis.geopolitical.score,
            EngineId.NEWS: analysis.news.score,
        }
        for engine_id, weight in analysis.regime.dynamic_weights.items():
            component = Decimal(values[engine_id]) * weight
            weighted_components[engine_id] = component
            total += component
        final_score = max(0, min(100, round(total)))
        return InvestmentScore(
            score=final_score,
            interpretation=_score_interpretation(final_score),
            weighted_components=weighted_components,
        )


class DecisionEngine:
    def __init__(self, config: DecisionEngineConfig) -> None:
        self._config = config

    def decide(self, context: DecisionContext) -> DecisionReport:
        now = datetime.now(UTC)
        trace = _build_decision_trace(context)
        confidence = trace.posterior_confidence
        recommendation = self._recommendation(context, confidence)
        evidence = _collect_supporting_evidence(context, recommendation)
        contradiction = _collect_contradicting_evidence(context, recommendation)
        risks = _collect_risks(context)
        expected_move_value = context.technical.expected_move_usd or Decimal("0")
        direction = _expected_direction(recommendation, context.technical.bias)
        return DecisionReport(
            recommendation_id=f"REC-{now.strftime('%Y%m%d-%H%M%S-%f')}-{uuid.uuid4().hex[:6].upper()}",
            recommendation=recommendation,
            investment_score=context.investment_score.score,
            opportunity_score=context.opportunity.opportunity_score,
            confidence=confidence,
            expected_move=ExpectedMove(
                direction=direction,
                min_usd=expected_move_value if expected_move_value else None,
                max_usd=(expected_move_value * Decimal("1.5")) if expected_move_value else None,
                summary=_expected_move_summary(recommendation, expected_move_value),
            ),
            expected_holding_period=_holding_period(context.regime.regime),
            market_regime=context.regime.regime,
            supporting_evidence=evidence,
            contradicting_evidence=contradiction,
            risk_summary=risks,
            invalidation_conditions=_invalidation_conditions(context),
            support_resistance=context.technical.support_resistance,
            explanation=_explanation(context, recommendation, confidence, trace),
            research_desk_report=context.research_desk_report,
            decision_trace=trace,
            timestamp=now,
        )

    def _recommendation(self, context: DecisionContext, confidence: int) -> Recommendation:
        if not context.opportunity.passed:
            return Recommendation.WAIT
        score = context.investment_score.score
        if confidence < self._config.thresholds.minimum_confidence_for_action:
            return Recommendation.WAIT
        if score >= 90 and _positive_alignment(context):
            return Recommendation.STRONG_BUY
        if _positive_alignment(context):
            return Recommendation.BUY
        if score <= 9 and _negative_alignment(context):
            return Recommendation.STRONG_SELL
        if _negative_alignment(context):
            return Recommendation.TAKE_PROFIT
        return Recommendation.WAIT


def _aggregate_confidence(context: DecisionContext) -> int:
    return _aggregate_analysis_confidence(
        AnalysisBundle(
            market_data=context.market_data,
            technical=context.technical,
            fundamental=context.fundamental,
            news=context.news,
            geopolitical=context.geopolitical,
            institutional=context.institutional,
            regime=context.regime,
        )
    )


def _build_decision_trace(context: DecisionContext) -> DecisionTrace:
    """Apply bounded evidence updates while leaving recommendation rules authoritative."""
    analyses = (
        context.technical,
        context.fundamental,
        context.institutional,
        context.news,
        context.geopolitical,
        context.regime,
    )
    base_confidence = _aggregate_confidence(context)
    votes = tuple(_bias_vote(analysis.bias) for analysis in analyses)
    consensus = _consensus_vote(votes)
    aligned_reliability = Decimal("0")
    conflicting_reliability = Decimal("0")
    for analysis, vote in zip(analyses, votes, strict=True):
        reliability = Decimal(analysis.confidence.value) / Decimal("100")
        if analysis.status != ContractStatus.SUCCESS:
            reliability *= Decimal("0.25")
        if consensus and vote == consensus:
            aligned_reliability += reliability
        elif consensus and vote and vote != consensus:
            conflicting_reliability += reliability
    total_directional_reliability = aligned_reliability + conflicting_reliability
    alignment = (
        (aligned_reliability - conflicting_reliability) / total_directional_reliability
        if total_directional_reliability
        else Decimal("0")
    )
    posterior_before_penalties = _bayesian_posterior(base_confidence, alignment)
    evidence_weight_adjustment = posterior_before_penalties - base_confidence
    missing = tuple(analysis for analysis in analyses if analysis.status != ContractStatus.SUCCESS)
    committee = (
        context.research_desk_report.committee_report
        if context.research_desk_report is not None
        else None
    )
    contradiction_count = sum(1 for vote in votes if consensus and vote and vote != consensus)
    if committee is not None:
        contradiction_count += len(committee.conflicting_evidence)
    contradiction_penalty = min(20, contradiction_count * 3)
    missing_evidence_penalty = min(20, len(missing) * 4)
    requested_committee_adjustment = committee.confidence_adjustment if committee else 0
    committee_adjustment = _bounded_committee_adjustment(requested_committee_adjustment)
    posterior_confidence = _clamp_confidence(
        posterior_before_penalties
        - contradiction_penalty
        - missing_evidence_penalty
        + committee_adjustment
    )
    attributions = (
        ConfidenceAttribution(
            source="Deterministic evidence prior",
            contribution=base_confidence,
            rationale="Average confidence from the independent deterministic engines.",
        ),
        ConfidenceAttribution(
            source="Evidence alignment update",
            contribution=evidence_weight_adjustment,
            rationale=(
                "Bayesian-style likelihood update from the reliability-weighted directional "
                "alignment of available engine evidence."
            ),
        ),
        ConfidenceAttribution(
            source="Contradictory evidence",
            contribution=-contradiction_penalty,
            rationale="Penalty for conflicting deterministic or committee evidence.",
        ),
        ConfidenceAttribution(
            source="Missing evidence",
            contribution=-missing_evidence_penalty,
            rationale="Penalty for engines without a successful, current evidence result.",
        ),
        ConfidenceAttribution(
            source="Investment committee",
            contribution=committee_adjustment,
            rationale=(
                "Bounded advisory adjustment from validated committee reasoning."
                if committee is not None and committee.provider != "deterministic_fallback"
                else "Conservative adjustment because validated committee reasoning is unavailable."
            ),
        ),
    )
    return DecisionTrace(
        base_confidence=base_confidence,
        posterior_confidence=posterior_confidence,
        evidence_weight_adjustment=evidence_weight_adjustment,
        contradiction_penalty=contradiction_penalty,
        missing_evidence_penalty=missing_evidence_penalty,
        committee_adjustment=committee_adjustment,
        confidence_attribution=attributions,
        why_not_buy=(
            committee.why_not_buy
            if committee is not None
            else _deterministic_why_not_buy(context)
        ),
        why_not_sell=(
            committee.why_not_sell
            if committee is not None
            else _deterministic_why_not_sell(context)
        ),
        required_confirmations=_required_confirmations(context, missing, committee),
        alternative_scenarios=(committee.alternative_scenarios if committee is not None else ()),
    )


def _bias_vote(bias: DirectionalBias) -> int:
    if bias == DirectionalBias.BULLISH:
        return 1
    if bias == DirectionalBias.BEARISH:
        return -1
    return 0


def _consensus_vote(votes: tuple[int, ...]) -> int:
    total = sum(votes)
    if total > 0:
        return 1
    if total < 0:
        return -1
    return 0


def _bayesian_posterior(prior_confidence: int, alignment: Decimal) -> int:
    """Use posterior odds = prior odds x a bounded evidence likelihood ratio."""
    prior = Decimal(max(1, min(99, prior_confidence))) / Decimal("100")
    prior_odds = prior / (Decimal("1") - prior)
    likelihood_ratio = max(Decimal("0.75"), min(Decimal("1.25"), Decimal("1") + alignment / 4))
    posterior_odds = prior_odds * likelihood_ratio
    posterior = posterior_odds / (Decimal("1") + posterior_odds)
    return _clamp_confidence(round(posterior * 100))


def _bounded_committee_adjustment(adjustment: int) -> int:
    return max(-15, min(10, adjustment))


def _clamp_confidence(value: int) -> int:
    return max(0, min(100, value))


def _required_confirmations(context: DecisionContext, missing, committee) -> tuple[str, ...]:
    confirmations = [risk.risk for risk in context.opportunity.blocking_risks]
    confirmations.extend(
        f"Restore successful {analysis.engine.value} evidence." for analysis in missing
    )
    if committee is not None:
        confirmations.extend(committee.required_confirmations)
    if not confirmations:
        confirmations.append("Maintain current cross-engine evidence alignment.")
    return tuple(dict.fromkeys(confirmations))[:16]


def _deterministic_why_not_buy(context: DecisionContext) -> str:
    if not context.opportunity.passed:
        return context.opportunity.reason
    return "A buy requires sustained cross-engine alignment and an action-quality confidence level."


def _deterministic_why_not_sell(context: DecisionContext) -> str:
    if context.technical.bias == DirectionalBias.BULLISH:
        return "Technical evidence remains constructive enough to avoid a sell conclusion."
    return "A sell requires broad bearish alignment and a high-quality downside opportunity."


def _aggregate_analysis_confidence(analysis: AnalysisBundle) -> int:
    values = (
        analysis.technical.confidence.value,
        analysis.fundamental.confidence.value,
        analysis.news.confidence.value,
        analysis.geopolitical.confidence.value,
        analysis.institutional.confidence.value,
        analysis.regime.confidence.value,
    )
    return max(0, min(100, round(sum(values) / len(values))))


def _high_risk_count(analysis: AnalysisBundle) -> int:
    risks = (
        *analysis.technical.risks,
        *analysis.fundamental.risks,
        *analysis.institutional.risks,
        *analysis.news.risks,
        *analysis.geopolitical.risks,
        *analysis.regime.risks,
    )
    return sum(
        1 for risk in risks if risk.severity in {EvidenceStrength.HIGH, EvidenceStrength.CRITICAL}
    )


def _collect_supporting_evidence(
    context: DecisionContext, recommendation: Recommendation
) -> tuple[EvidenceRecord, ...]:
    all_evidence = (
        *context.technical.evidence,
        *context.fundamental.evidence,
        *context.institutional.evidence,
        *context.news.evidence,
        *context.geopolitical.evidence,
        *context.regime.evidence,
    )
    committee_evidence = _committee_evidence(context)
    if recommendation in {Recommendation.BUY, Recommendation.STRONG_BUY, Recommendation.HOLD}:
        return (*committee_evidence, *all_evidence)[:10]
    return (
        EvidenceRecord(
            evidence_id="DECISION-DISCIPLINE-001",
            category="Decision Discipline",
            description=context.opportunity.reason,
            strength=EvidenceStrength.HIGH,
            confidence=100,
            source="Decision Engine",
        ),
        *committee_evidence,
        *all_evidence[:9],
    )[:10]


def _collect_contradicting_evidence(
    context: DecisionContext, recommendation: Recommendation
) -> tuple[EvidenceRecord, ...]:
    committee_conflicts = _committee_conflicts(context)
    if recommendation in {Recommendation.BUY, Recommendation.STRONG_BUY}:
        deterministic = tuple(
            evidence
            for evidence in (
                *context.fundamental.evidence,
                *context.news.evidence,
                *context.regime.evidence,
            )
            if "headwind" in evidence.description.lower()
            or "rejected" in evidence.description.lower()
        )
        return (*committee_conflicts, *deterministic)[:10]
    deterministic = tuple(
        evidence
        for evidence in (*context.technical.evidence, *context.institutional.evidence)
        if "supportive" in evidence.description.lower() or "rose" in evidence.description.lower()
    )
    return (*committee_conflicts, *deterministic)[:10]


def _committee_evidence(context: DecisionContext) -> tuple[EvidenceRecord, ...]:
    research = context.research_desk_report
    if research is None:
        return ()
    committee = research.committee_report
    if committee.provider == "deterministic_fallback":
        return ()
    return (
        EvidenceRecord(
            evidence_id=f"COMMITTEE-{committee.report_id[-90:]}",
            category="Investment Committee",
            description=committee.summary[:500],
            strength=(
                EvidenceStrength.HIGH if committee.confidence >= 70 else EvidenceStrength.MEDIUM
            ),
            confidence=committee.confidence,
            source="AI Research Desk",
        ),
    )


def _committee_conflicts(context: DecisionContext) -> tuple[EvidenceRecord, ...]:
    research = context.research_desk_report
    if research is None:
        return ()
    committee = research.committee_report
    return tuple(
        EvidenceRecord(
            evidence_id=f"COMMITTEE-CONFLICT-{index + 1}",
            category="Committee Conflict",
            description=conflict[:500],
            strength=EvidenceStrength.MEDIUM,
            confidence=committee.confidence,
            source="AI Research Desk",
        )
        for index, conflict in enumerate(committee.conflicting_evidence[:4])
    )


def _collect_risks(context: DecisionContext) -> tuple[RiskRecord, ...]:
    risks = (
        *context.technical.risks,
        *context.fundamental.risks,
        *context.institutional.risks,
        *context.news.risks,
        *context.geopolitical.risks,
        *context.regime.risks,
        *context.opportunity.blocking_risks,
    )
    if risks:
        return risks[:10]
    return (
        RiskRecord(
            risk="No major risk blocker detected, but market uncertainty remains.",
            severity=EvidenceStrength.MEDIUM,
            probability=50,
        ),
    )


def _invalidation_conditions(context: DecisionContext) -> tuple[InvalidationCondition, ...]:
    support = context.technical.support_resistance.support
    resistance = context.technical.support_resistance.resistance
    conditions = []
    if support:
        conditions.append(
            InvalidationCondition(
                condition=(
                    f"Daily close below {support[0].price:.2f} invalidates " "the bullish setup."
                ),
                severity=NotificationPriority.HIGH,
            )
        )
    if resistance:
        conditions.append(
            InvalidationCondition(
                condition=(
                    f"Failure near {resistance[0].price:.2f} without follow-through "
                    "weakens upside evidence."
                ),
                severity=NotificationPriority.NORMAL,
            )
        )
    conditions.append(
        InvalidationCondition(
            condition=(
                "Unexpected hawkish macro surprise or sharp dollar rally " "requires reassessment."
            ),
            severity=NotificationPriority.HIGH,
        )
    )
    return tuple(conditions)


def _positive_alignment(context: DecisionContext) -> bool:
    bullish = DirectionalBias.BULLISH
    return (
        sum(
            1
            for bias in (
                context.technical.bias,
                context.fundamental.bias,
                context.institutional.bias,
                context.regime.bias,
            )
            if bias == bullish
        )
        >= 2
    )


def _negative_alignment(context: DecisionContext) -> bool:
    bearish = DirectionalBias.BEARISH
    return (
        sum(
            1
            for bias in (
                context.technical.bias,
                context.fundamental.bias,
                context.institutional.bias,
                context.regime.bias,
            )
            if bias == bearish
        )
        >= 2
    )


def _score_interpretation(score: int) -> str:
    if score >= 90:
        return "Exceptional opportunity"
    if score >= 80:
        return "Strong opportunity"
    if score >= 70:
        return "Constructive opportunity"
    if score >= 50:
        return "Hold-quality environment"
    if score >= 30:
        return "Wait-quality environment"
    if score >= 10:
        return "Take-profit risk zone"
    return "Strong sell risk zone"


def _expected_direction(recommendation: Recommendation, technical_bias: DirectionalBias) -> str:
    if recommendation in {Recommendation.BUY, Recommendation.STRONG_BUY}:
        return "UP"
    if recommendation in {Recommendation.TAKE_PROFIT, Recommendation.STRONG_SELL}:
        return "DOWN"
    if technical_bias == DirectionalBias.BULLISH:
        return "UP"
    if technical_bias == DirectionalBias.BEARISH:
        return "DOWN"
    return "SIDEWAYS"


def _expected_move_summary(recommendation: Recommendation, expected_move: Decimal) -> str:
    if recommendation == Recommendation.WAIT:
        return "No action-quality move is confirmed; preserve discipline."
    return (
        f"Estimated tactical move is approximately {expected_move:.2f} USD under current evidence."
    )


def _holding_period(regime: MarketRegime) -> str:
    if regime == MarketRegime.EVENT_DRIVEN:
        return "1 hour to 1 day"
    if regime == MarketRegime.HIGH_VOLATILITY:
        return "1 hour to 3 days"
    if regime in {MarketRegime.BULL, MarketRegime.BEAR, MarketRegime.RISK_OFF}:
        return "2-10 days"
    return "1-4 weeks"


def _explanation(
    context: DecisionContext,
    recommendation: Recommendation,
    confidence: int,
    trace: DecisionTrace,
) -> str:
    committee_summary = ""
    if context.research_desk_report is not None:
        committee = context.research_desk_report.committee_report
        committee_summary = f" Committee view: {committee.summary[:500]}"
    return (
        f"Decision Engine recommends {recommendation.value} with {confidence}% "
        "evidence confidence. "
        f"Investment score is {context.investment_score.score}/100 and opportunity score is "
        f"{context.opportunity.opportunity_score}/100. Regime is {context.regime.regime.value}. "
        f"Primary discipline note: {context.opportunity.reason}"
        f" Confidence trace: base {trace.base_confidence}%, alignment "
        f"{trace.evidence_weight_adjustment:+d}, contradictions "
        f"-{trace.contradiction_penalty}, missing evidence "
        f"-{trace.missing_evidence_penalty}, committee {trace.committee_adjustment:+d}."
        f"{committee_summary}"
    )
