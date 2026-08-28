from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from app.domain.common import DomainModel, EvidenceStrength, utc_now
from app.domain.enums import Recommendation


class AgentRole(StrEnum):
    MACRO_ECONOMIST = "macro_economist"
    FEDERAL_RESERVE_ANALYST = "federal_reserve_analyst"
    TECHNICAL_ANALYST = "technical_analyst"
    GEOPOLITICAL_ANALYST = "geopolitical_analyst"
    NEWS_ANALYST = "news_analyst"
    INSTITUTIONAL_ANALYST = "institutional_analyst"
    ETF_FLOW_ANALYST = "etf_flow_analyst"
    RISK_ANALYST = "risk_analyst"
    DEVILS_ADVOCATE = "devils_advocate"
    INVESTMENT_COMMITTEE_CHAIR = "investment_committee_chair"


class AIGoldImpactDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


class AIContext(DomainModel):
    context_id: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=500)
    facts: dict[str, Any] = Field(default_factory=dict)
    retrieved_record_ids: tuple[str, ...] = Field(default_factory=tuple)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AI context timestamp must be timezone-aware")
        return value


class PromptTemplate(DomainModel):
    template_id: str = Field(min_length=1, max_length=160)
    role: AgentRole
    version: str = Field(default="1.0", min_length=1, max_length=40)
    system_prompt: str = Field(min_length=1, max_length=5000)
    output_schema_name: str = Field(min_length=1, max_length=160)


class AIResponseEnvelope(DomainModel):
    role: AgentRole
    prompt_version: str = Field(min_length=1, max_length=40)
    raw_json: str = Field(min_length=1, max_length=20_000)
    validated: bool
    validation_error: str | None = Field(default=None, max_length=1000)


class AINewsImpactAssessment(DomainModel):
    severity: int = Field(ge=0, le=100)
    gold_impact_direction: AIGoldImpactDirection
    gold_impact_magnitude: int = Field(ge=0, le=100)
    reliability: int = Field(ge=0, le=100)
    reasoning: str = Field(min_length=1, max_length=1000)


class AIProviderUsage(DomainModel):
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    runtime_ms: int = Field(default=0, ge=0)
    escalation_reason: str | None = Field(default=None, max_length=500)
    context_tokens_before: int | None = Field(default=None)
    context_tokens_after: int | None = Field(default=None)
    evidence_selected: int | None = Field(default=None)
    evidence_dropped: int | None = Field(default=None)
    narratives_selected: int | None = Field(default=None)
    items_dropped_by_budget: int | None = Field(default=None)
    retry_count: int | None = Field(default=None)
    queue_wait_ms: int | None = Field(default=None)
    fallback_reason: str | None = Field(default=None)


class ProviderAttempt(DomainModel):
    """One provider/model attempt made while resolving an LLM completion.

    Recorded for every attempt, whether it succeeded, failed, or was skipped by the
    circuit breaker, so the full attempt trail is available for debugging and can
    optionally be surfaced on the final report â€” not just the provider that won.
    """

    provider: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=160)
    status: str = Field(min_length=1, max_length=40)
    latency_ms: int | None = Field(default=None, ge=0)
    error: str | None = Field(default=None, max_length=1000)


class AnalystEvidence(DomainModel):
    evidence_id: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    claim: str = Field(min_length=1, max_length=500)
    direction: AIGoldImpactDirection
    strength: EvidenceStrength = EvidenceStrength.MEDIUM
    confidence: int = Field(ge=0, le=100)
    source_fact_keys: tuple[str, ...] = Field(default_factory=tuple)


class AnalystReportPayload(DomainModel):
    summary: str = Field(min_length=1, max_length=2000)
    bullish_arguments: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    bearish_arguments: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    confidence: int = Field(ge=0, le=100)
    risks: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    recommendation: Recommendation
    structured_evidence: tuple[AnalystEvidence, ...] = Field(default_factory=tuple, max_length=10)
    missing_evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    required_confirmations: tuple[str, ...] = Field(default_factory=tuple, max_length=8)


class AnalystReport(AnalystReportPayload):
    report_id: str = Field(min_length=1, max_length=160)
    role: AgentRole
    context_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=80)
    generated_at: datetime = Field(default_factory=utc_now)
    fallback_reason: str | None = Field(default=None, max_length=1000)
    usage: AIProviderUsage | None = None

    @field_validator("generated_at")
    @classmethod
    def require_generated_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value


class CommitteeReportPayload(DomainModel):
    final_recommendation: Recommendation
    confidence: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=2500)
    disagreements: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    missing_evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    weak_evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    conflicting_evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    required_confirmations: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    confidence_adjustment: int = Field(ge=-30, le=30)
    why_not_buy: str = Field(min_length=1, max_length=1200)
    why_not_sell: str = Field(min_length=1, max_length=1200)
    alternative_scenarios: tuple[str, ...] = Field(default_factory=tuple, max_length=8)

    @field_validator(
        "disagreements",
        "missing_evidence",
        "weak_evidence",
        "conflicting_evidence",
        "required_confirmations",
        "alternative_scenarios",
        mode="before",
    )
    @classmethod
    def _coerce_object_to_string_list(cls, value: Any) -> Any:
        """Defense-in-depth for a recurring LLM failure mode: despite an explicit prompt
        instruction to return a flat array, models (observed repeatedly with Gemini) have
        grouped these fields into an object instead - e.g. {"Bullish Reversal": "If support
        holds near 3360, a reversal is possible."} instead of ["If support holds near 3360,
        a reversal is possible."]. Rather than let that hard-fail contract validation and
        burn an entire provider fallback over a formatting slip, flatten it into the shape
        the schema expects. Prompting alone has not reliably stopped this on its own.
        """
        if isinstance(value, dict):
            return [f"{key}: {item}" for key, item in value.items()]
        return value


class CommitteeVoteSnapshot(DomainModel):
    """One committee member's vote, captured for downstream consumers (e.g. the
    UnifiedDecision and by-narrative attribution) without leaking LLM internals."""

    member_name: str = Field(min_length=1, max_length=80)
    direction: str = Field(min_length=1, max_length=10)
    confidence: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(default="", max_length=1500)


class InvestmentCommitteeReport(CommitteeReportPayload):
    report_id: str = Field(min_length=1, max_length=160)
    context_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=80)
    generated_at: datetime = Field(default_factory=utc_now)
    fallback_reason: str | None = Field(default=None, max_length=1000)
    usage: AIProviderUsage | None = None
    provider_attempts: tuple[ProviderAttempt, ...] = Field(default_factory=tuple, max_length=20)
    committee_votes: tuple[CommitteeVoteSnapshot, ...] = Field(
        default_factory=tuple, max_length=8
    )

    @field_validator("generated_at")
    @classmethod
    def require_committee_generated_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value


class ResearchDeskReport(DomainModel):
    analyst_reports: tuple[AnalystReport, ...] = Field(min_length=1)
    committee_report: InvestmentCommitteeReport
    generated_at: datetime = Field(default_factory=utc_now)

    @field_validator("generated_at")
    @classmethod
    def require_research_generated_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value


