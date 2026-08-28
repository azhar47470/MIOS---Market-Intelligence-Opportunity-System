from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, field_validator

from app.domain.ai import ResearchDeskReport
from app.domain.common import (
    ConfidenceScore,
    ContractMetadata,
    ContractStatus,
    DomainModel,
    EvidenceRecord,
    RiskRecord,
)
from app.domain.enums import Recommendation
from app.domain.market_data import (
    CotPositioningSnapshot,
    EconomicCalendarEvent,
    EtfFlowSnapshot,
    MacroSeriesObservation,
    MarketQuote,
    NewsArticle,
    OhlcBar,
)
from app.domain.notification_models import (
    ExpectedMove,
    InvalidationCondition,
    SupportResistanceLevels,
)


class EngineId(StrEnum):
    MARKET_DATA = "market_data"
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    NEWS = "news"
    GEOPOLITICAL = "geopolitical"
    INSTITUTIONAL = "institutional"
    MARKET_REGIME = "market_regime"
    OPPORTUNITY_FILTER = "opportunity_filter"
    INVESTMENT_SCORING = "investment_scoring"
    DECISION = "decision"
    BACKTESTING = "backtesting"
    PAPER_TRADING = "paper_trading"


class DirectionalBias(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"
    UNKNOWN = "UNKNOWN"


class MarketRegime(StrEnum):
    BULL = "BULL"
    BEAR = "BEAR"
    RANGE = "RANGE"
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    EVENT_DRIVEN = "EVENT_DRIVEN"
    UNKNOWN = "UNKNOWN"


class AnalysisResult(DomainModel):
    metadata: ContractMetadata = Field(default_factory=ContractMetadata)
    engine: EngineId
    status: ContractStatus
    confidence: ConfidenceScore
    quality: int = Field(ge=0, le=100)
    score: int = Field(ge=0, le=100)
    bias: DirectionalBias
    evidence: tuple[EvidenceRecord, ...] = Field(default_factory=tuple)
    risks: tuple[RiskRecord, ...] = Field(default_factory=tuple)
    execution_ms: int = Field(default=0, ge=0)


class MarketEventType(StrEnum):
    CENTRAL_BANK = "central_bank"
    ECONOMIC_DATA = "economic_data"
    GEOPOLITICAL = "geopolitical"
    INSTITUTIONAL = "institutional"
    MARKET_MOVE = "market_move"
    GENERAL = "general"


class MarketEvent(DomainModel):
    """One story as covered across sources, with cross-source verification metadata.

    An event is confirmed when an authoritative outlet (tier <= 2) reported it AND at
    least one other distinct source corroborates it; confidence scales with source
    breadth and tier diversity.
    """

    event_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    event_type: MarketEventType = MarketEventType.GENERAL
    article_ids: tuple[str, ...] = Field(default_factory=tuple)
    sources: tuple[str, ...] = Field(default_factory=tuple)
    confidence: float = Field(ge=0.0, le=1.0)
    is_confirmed: bool = False
    best_tier: int = Field(default=5, ge=1, le=5)
    tier_diversity: int = Field(default=1, ge=1)
    has_authoritative: bool = False
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class MarketNarrative(DomainModel):
    """A durable market narrative assembled from one or more verified events."""

    narrative_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    event_ids: tuple[str, ...] = Field(default_factory=tuple)
    article_ids: tuple[str, ...] = Field(default_factory=tuple)
    strength: float = Field(ge=0.0, le=1.0)


class MarketDataSnapshot(DomainModel):
    quote: MarketQuote | None = None
    bars: tuple[OhlcBar, ...] = Field(default_factory=tuple)
    dxy_observations: tuple[MacroSeriesObservation, ...] = Field(default_factory=tuple)
    macro_observations: tuple[MacroSeriesObservation, ...] = Field(default_factory=tuple)
    economic_events: tuple[EconomicCalendarEvent, ...] = Field(default_factory=tuple)
    news_articles: tuple[NewsArticle, ...] = Field(default_factory=tuple)
    geopolitical_articles: tuple[NewsArticle, ...] = Field(default_factory=tuple)
    cot_positioning: tuple[CotPositioningSnapshot, ...] = Field(default_factory=tuple)
    gld_flow: EtfFlowSnapshot | None = None
    provider_errors: dict[str, str] = Field(default_factory=dict)
    events: tuple[MarketEvent, ...] = Field(default_factory=tuple)
    narratives: tuple[MarketNarrative, ...] = Field(default_factory=tuple)
    collected_at: datetime

    @field_validator("collected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware")
        return value


class TechnicalAnalysis(AnalysisResult):
    trend_strength: int = Field(ge=0, le=100)
    momentum_score: int = Field(ge=0, le=100)
    volatility_score: int = Field(ge=0, le=100)
    support_resistance: SupportResistanceLevels
    latest_close: Decimal | None = None
    expected_move_usd: Decimal | None = None


class FundamentalAnalysis(AnalysisResult):
    macro_narrative: str = Field(min_length=1, max_length=1000)
    dollar_bias: DirectionalBias
    high_impact_event_count: int = Field(ge=0)


class NewsAnalysis(AnalysisResult):
    analyzed_articles: int = Field(ge=0)
    high_severity_events: int = Field(ge=0)


class GeopoliticalAnalysis(AnalysisResult):
    risk_score: int = Field(ge=0, le=100)
    conflict_status: str = Field(min_length=1, max_length=500)
    expected_market_impact: DirectionalBias


class InstitutionalAnalysis(AnalysisResult):
    positioning_summary: str = Field(min_length=1, max_length=1000)
    etf_flow_score: int = Field(ge=0, le=100)
    cot_score: int = Field(ge=0, le=100)


class MarketRegimeAnalysis(AnalysisResult):
    regime: MarketRegime
    dynamic_weights: dict[EngineId, Decimal]


class OpportunityAssessment(DomainModel):
    passed: bool
    opportunity_score: int = Field(ge=0, le=100)
    reason: str = Field(min_length=1, max_length=1000)
    required_action: Recommendation = Recommendation.WAIT
    blocking_risks: tuple[RiskRecord, ...] = Field(default_factory=tuple)


class InvestmentScore(DomainModel):
    score: int = Field(ge=0, le=100)
    interpretation: str = Field(min_length=1, max_length=200)
    weighted_components: dict[EngineId, Decimal]


class EngineBreakdown(DomainModel):
    engine: EngineId
    status: ContractStatus
    score: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    runtime_ms: int = Field(default=0, ge=0)
    evidence: tuple[EvidenceRecord, ...] = Field(default_factory=tuple)


class AnalysisBundle(DomainModel):
    market_data: MarketDataSnapshot
    technical: TechnicalAnalysis
    fundamental: FundamentalAnalysis
    news: NewsAnalysis
    geopolitical: GeopoliticalAnalysis
    institutional: InstitutionalAnalysis
    regime: MarketRegimeAnalysis


class DecisionContext(DomainModel):
    market_data: MarketDataSnapshot
    technical: TechnicalAnalysis
    fundamental: FundamentalAnalysis
    news: NewsAnalysis
    geopolitical: GeopoliticalAnalysis
    institutional: InstitutionalAnalysis
    regime: MarketRegimeAnalysis
    opportunity: OpportunityAssessment
    investment_score: InvestmentScore
    research_desk_report: ResearchDeskReport | None = None


class ConfidenceAttribution(DomainModel):
    source: str = Field(min_length=1, max_length=120)
    contribution: int = Field(ge=-100, le=100)
    rationale: str = Field(min_length=1, max_length=500)


class DecisionTrace(DomainModel):
    base_confidence: int = Field(ge=0, le=100)
    posterior_confidence: int = Field(ge=0, le=100)
    evidence_weight_adjustment: int = Field(ge=-100, le=100)
    contradiction_penalty: int = Field(ge=0, le=100)
    missing_evidence_penalty: int = Field(ge=0, le=100)
    committee_adjustment: int = Field(ge=-100, le=100)
    confidence_attribution: tuple[ConfidenceAttribution, ...] = Field(min_length=1)
    why_not_buy: str = Field(min_length=1, max_length=1200)
    why_not_sell: str = Field(min_length=1, max_length=1200)
    required_confirmations: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    alternative_scenarios: tuple[str, ...] = Field(default_factory=tuple, max_length=12)


class PullbackRiskReport(DomainModel):
    score: int = Field(ge=0, le=100)
    level: str
    directional_context: str
    drivers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

class ModePolicyPresentation(DomainModel):
    mode: str
    actionable: bool
    action: str
    reason: str
    is_wait: bool
    confidence: int
    expected_move: str
    entry: str | None = None
    take_profit: str | None = None
    stop_loss: str | None = None
    allocation: str | None = None
    risk: str | None = None
    horizon: str | None = None


class DecisionReport(DomainModel):
    recommendation_id: str = Field(min_length=1, max_length=120)
    recommendation: Recommendation
    investment_score: int = Field(ge=0, le=100)
    opportunity_score: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    expected_move: ExpectedMove
    expected_holding_period: str = Field(min_length=1, max_length=80)
    market_regime: MarketRegime
    supporting_evidence: tuple[EvidenceRecord, ...] = Field(min_length=1)
    contradicting_evidence: tuple[EvidenceRecord, ...] = Field(default_factory=tuple)
    risk_summary: tuple[RiskRecord, ...] = Field(min_length=1)
    invalidation_conditions: tuple[InvalidationCondition, ...] = Field(min_length=1)
    support_resistance: SupportResistanceLevels
    explanation: str = Field(min_length=1, max_length=2000)
    engine_breakdown: tuple[EngineBreakdown, ...] = Field(default_factory=tuple)
    research_desk_report: ResearchDeskReport | None = None
    pullback_risk_report: PullbackRiskReport | None = None
    decision_trace: DecisionTrace | None = None
    provider_statuses: dict[str, ContractStatus] = Field(default_factory=dict)
    mode_policy_results: tuple[ModePolicyPresentation, ...] | None = None
    mode_policies: dict | None = Field(default=None, exclude=True)
    spot_price: float | None = Field(default=None, description="Actual spot price at decision time")
    pipeline_telemetry: dict[str, int] | None = Field(default=None, description="Telemetry counts for UI")
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value
