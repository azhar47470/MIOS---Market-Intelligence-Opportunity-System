from datetime import UTC, datetime

from app.ai.agents.llm_client import AIProviderError, LLMJsonClient
from app.ai.committee import AdversarialCommittee
from app.ai.context_builder import AIContextBuilder
from app.ai.rag import KnowledgeRetriever
from app.ai.validator import AIJsonValidator
from app.application.ai_research_config import SPECIALIST_ROLES, AIResearchConfig
from app.domain.ai import (
    AgentRole,
    AIGoldImpactDirection,
    AnalystEvidence,
    AnalystReport,
    InvestmentCommitteeReport,
    ProviderAttempt,
    ResearchDeskReport,
)
from app.domain.common import ContractStatus
from app.domain.enums import Recommendation
from app.domain.intelligence import AnalysisBundle, DirectionalBias, MarketRegime

# Risk-elevated regime states that always require deep reasoning. Trend and liquidity
# regimes (BULL, BEAR, RANGE, RISK_ON, LOW_VOLATILITY) are treated as stable and only
# escalate when a separate escalation condition fires.
_ESCALATION_REGIMES = frozenset({
    MarketRegime.EVENT_DRIVEN,
    MarketRegime.RISK_OFF,
    MarketRegime.HIGH_VOLATILITY,
    MarketRegime.UNKNOWN,
})


class AIResearchDesk:
    """Coordinates an adversarial four-member committee vote over validated deterministic facts.

    Every specialist report is built directly from the deterministic engines (Technical,
    Fundamental, Institutional, News, Geopolitical, Regime) — no per-specialist LLM call is
    made. The only LLM calls are the committee member votes: a macro strategist, a
    tactical trader, and a contrarian risk analyst (distinct temperatures, all
    preferring Groq) vote alongside a rule-based deterministic anchor. Members
    deliberate over the shared provider chain with cycle-level locking — Groq-first
    when no escalation fires, OpenCode/Laguna-first when the desk escalates for deep
    reasoning, with Ollama and Gemini as fallbacks. The weighted consensus is mapped
    back onto the InvestmentCommitteeReport contract the DecisionEngine consumes, so
    the downstream pipeline is unchanged.
    """

    def __init__(
        self,
        *,
        config: AIResearchConfig,
        client: LLMJsonClient,
        context_builder: AIContextBuilder | None = None,
        validator: AIJsonValidator | None = None,
        knowledge_retriever: KnowledgeRetriever | None = None,
    ) -> None:
        self._config = config
        self._context_builder = context_builder or AIContextBuilder()
        self._validator = validator or AIJsonValidator()
        self._knowledge_retriever = knowledge_retriever
        self._committee = AdversarialCommittee(client=client, config=config)


    def _evaluate_escalation(self, bundle: AnalysisBundle) -> tuple[bool, str | None]:
        esc_config = getattr(self._config, "escalation", None)
        stability_threshold = esc_config.stability_threshold if esc_config else 0.4
        geo_shock_threshold = esc_config.geopolitical_shock_threshold if esc_config else 30.0
        ambiguous_margin = esc_config.ambiguous_margin if esc_config else 10.0

        if bundle.regime:
            if bundle.regime.confidence.value < (stability_threshold * 100):
                return True, "Low decision stability"
            if bundle.regime.regime in _ESCALATION_REGIMES:
                return True, f"Regime transition: {bundle.regime.regime.value}"
        
        if bundle.geopolitical and bundle.geopolitical.score < geo_shock_threshold:
            return True, "Geopolitical shock detected"

        if bundle.technical and bundle.fundamental:
            if abs(bundle.technical.score - bundle.fundamental.score) > 60:
                return True, "Strong engine disagreement (Tech vs Fund)"
        
        if bundle.technical:
            if abs(bundle.technical.score - 50) < ambiguous_margin:
                return True, "Ambiguous technical confidence"

        # Critical evidence carries no direction on the EvidenceRecord contract, so any
        # CRITICAL-strength engine evidence (no-data, extreme pullback risk, stale data)
        # conservatively forces deep reasoning.
        for analysis in [bundle.technical, bundle.fundamental, bundle.institutional]:
            if analysis and any(ev.strength.value == "CRITICAL" for ev in analysis.evidence):
                return True, "Critical opposing evidence"

        return False, None

    def analyze(self, bundle: AnalysisBundle) -> ResearchDeskReport:
        import logging
        logger = logging.getLogger(__name__)
        logger.info('[COMMITTEE] ResearchDesk entered')
        reports = tuple(self._deterministic_report(role, bundle) for role in SPECIALIST_ROLES)
        combined_context = self._context_builder.for_research_desk(bundle)
        if self._knowledge_retriever is not None:
            combined_context = self._knowledge_retriever.enrich(
                combined_context,
                query=_knowledge_query(bundle),
                limit=self._config.max_evidence_per_report + 2,
            )
        try:
            if not self._config.enabled:
                raise AIProviderError("AI research is disabled by configuration.")
            
            requires_deep_reasoning, escalation_reason = self._evaluate_escalation(bundle)
            logger.info(f'[COMMITTEE] Escalation decision = {requires_deep_reasoning}')
            logger.info(f'[COMMITTEE] Escalation reason = {escalation_reason}')
            committee = self._committee.deliberate(combined_context, reports, requires_deep_reasoning=requires_deep_reasoning)
            
            # Record telemetry inside the report
            if committee.usage:
                committee = committee.model_copy(update={
                    "usage": committee.usage.model_copy(update={"escalation_reason": escalation_reason})
                })
                
            telemetry = combined_context.facts.get("_telemetry", {})
            if committee.usage and telemetry:
                updates = {
                    "context_tokens_before": telemetry.get("tokens_before"),
                    "context_tokens_after": telemetry.get("tokens_after"),
                    "evidence_selected": telemetry.get("evidence_selected"),
                    "evidence_dropped": telemetry.get("evidence_dropped"),
                    "narratives_selected": telemetry.get("narratives_selected"),
                    "items_dropped_by_budget": telemetry.get("items_dropped_by_budget")
                }
                committee = committee.model_copy(update={
                    "usage": committee.usage.model_copy(update={k: v for k, v in updates.items() if v is not None})
                })

        except AIProviderError as error:
            logger.info(f'[COMMITTEE] FALLBACK TO DETERMINISTIC = {error}')
            committee = self._fallback_committee(
                combined_context.context_id,
                reports,
                str(error),
                error.attempts,
            )
        return ResearchDeskReport(
            analyst_reports=reports,
            committee_report=committee,
            generated_at=datetime.now(UTC),
        )

    def _deterministic_report(self, role: AgentRole, bundle: AnalysisBundle) -> AnalystReport:
        """Build one specialist's AnalystReport straight from its deterministic
        engine's output. No LLM call happens here - this is the normal, intended
        path now, not a degraded fallback, so confidence is used as-is rather than
        capped the way a genuine AI-failure fallback is.

        provider is deliberately still "deterministic_fallback" (not a new label):
        NewsIntelligenceEngine and GeopoliticalIntelligenceEngine check that exact
        string to decide whether to make their own direct AI call (a separate,
        pre-existing mechanism this leaves alone). A new label would make them
        treat this as a real specialist AI synthesis and skip - or on the second
        orchestrator pass, overwrite - their own AI attempt.
        """
        context_id = f"{role.value}-{bundle.market_data.collected_at.isoformat()}"
        result = _analysis_for(role, bundle)
        direction = _direction_from_bias(result.bias)
        evidence = tuple(
            AnalystEvidence(
                evidence_id=f"{role.value}-{index + 1}",
                category=item.category,
                claim=item.description,
                direction=direction,
                strength=item.strength,
                confidence=item.confidence,
                source_fact_keys=(item.evidence_id,),
            )
            for index, item in enumerate(result.evidence[: self._config.max_evidence_per_report])
        )
        return AnalystReport(
            report_id=(
                f"DET-{role.value.upper()}-"
                f"{bundle.market_data.collected_at.strftime('%H%M%S%f')}"
            ),
            role=role,
            context_id=context_id,
            provider="deterministic_fallback",
            summary=(
                f"{role.value} evidence synthesized directly from deterministic engine "
                "output; per-specialist AI calls were removed so only the committee "
                "stage makes an LLM call."
            ),
            bullish_arguments=tuple(
                item.description
                for item in result.evidence
                if result.bias == DirectionalBias.BULLISH
            )[:4],
            bearish_arguments=tuple(
                item.description
                for item in result.evidence
                if result.bias == DirectionalBias.BEARISH
            )[:4],
            confidence=result.confidence.value,
            risks=tuple(item.risk for item in result.risks)[:8],
            recommendation=_recommendation_from_result(result.bias, result.score),
            structured_evidence=evidence,
            missing_evidence=(
                (f"Underlying {role.value} status is {result.status.value}.",)
                if result.status != ContractStatus.SUCCESS
                else ()
            ),
            required_confirmations=(),
            fallback_reason=None,
        )

    def _fallback_committee(
        self,
        context_id: str,
        reports: tuple[AnalystReport, ...],
        reason: str,
        attempts: tuple[ProviderAttempt, ...] = (),
    ) -> InvestmentCommitteeReport:
        low_confidence_reports = tuple(
            report.role.value
            for report in reports
            if report.confidence <= self._config.fallback_confidence_cap
        )
        return InvestmentCommitteeReport(
            report_id=f"AI-FALLBACK-COMMITTEE-{context_id[-16:]}",
            context_id=context_id,
            provider="deterministic_fallback",
            final_recommendation=Recommendation.WAIT,
            confidence=min(
                self._config.fallback_confidence_cap,
                (
                    round(sum(report.confidence for report in reports) / len(reports))
                    if reports
                    else 0
                ),
            ),
            summary=(
                "Investment committee AI reasoning is unavailable. The deterministic Decision "
                "Engine remains authoritative and should preserve discipline."
            ),
            disagreements=(),
            missing_evidence=low_confidence_reports,
            weak_evidence=low_confidence_reports,
            conflicting_evidence=(),
            required_confirmations=("Validated investment committee reasoning is unavailable.",),
            confidence_adjustment=self._config.committee_fallback_confidence_adjustment,
            why_not_buy="No validated committee confirmation is available.",
            why_not_sell="No validated committee confirmation is available.",
            alternative_scenarios=("Wait for validated evidence and committee availability.",),
            fallback_reason=reason[:1000],
            provider_attempts=attempts,
        )


def _knowledge_query(bundle: AnalysisBundle) -> str:
    regime = bundle.regime.regime.value
    return (
        f"gold {regime} regime technical macro dollar yields inflation "
        "central bank geopolitics safe haven institutional flows"
    )


def _analysis_for(role: AgentRole, bundle: AnalysisBundle):
    if role == AgentRole.TECHNICAL_ANALYST:
        return bundle.technical
    if role in {AgentRole.MACRO_ECONOMIST, AgentRole.FEDERAL_RESERVE_ANALYST}:
        return bundle.fundamental
    if role in {AgentRole.INSTITUTIONAL_ANALYST, AgentRole.ETF_FLOW_ANALYST}:
        return bundle.institutional
    if role == AgentRole.NEWS_ANALYST:
        return bundle.news
    if role == AgentRole.GEOPOLITICAL_ANALYST:
        return bundle.geopolitical
    if role == AgentRole.RISK_ANALYST:
        return bundle.regime
    raise ValueError(f"Unsupported specialist role: {role.value}")


def _direction_from_bias(bias: DirectionalBias) -> AIGoldImpactDirection:
    if bias == DirectionalBias.BULLISH:
        return AIGoldImpactDirection.BULLISH
    if bias == DirectionalBias.BEARISH:
        return AIGoldImpactDirection.BEARISH
    if bias == DirectionalBias.MIXED:
        return AIGoldImpactDirection.MIXED
    return AIGoldImpactDirection.NEUTRAL


def _recommendation_from_result(bias: DirectionalBias, score: int) -> Recommendation:
    if bias == DirectionalBias.BULLISH and score >= 70:
        return Recommendation.BUY
    if bias == DirectionalBias.BEARISH and score <= 30:
        return Recommendation.TAKE_PROFIT
    if score >= 50:
        return Recommendation.HOLD
    return Recommendation.WAIT
