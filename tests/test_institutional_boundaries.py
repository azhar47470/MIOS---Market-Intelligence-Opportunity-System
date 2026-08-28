from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel

from app.ai.context_builder import AIContextBuilder
from app.ai.rag import KnowledgeRetriever
from app.ai.validator import AIJsonValidator
from app.application.engines.technical_engine import TechnicalIntelligenceEngine
from app.application.event_bus import InMemoryEventBus
from app.application.knowledge_base import KnowledgeBaseService
from app.backtesting.metrics import directional_hit_rate, wait_count
from app.backtesting.replay import HistoricalReplayer
from app.contracts.registry import export_contract_schemas
from app.domain.common import (
    ConfidenceScore,
    ContractStatus,
    EvidenceRecord,
    EvidenceStrength,
    RiskRecord,
)
from app.domain.enums import Recommendation
from app.domain.events import DomainEvent, EventType
from app.domain.intelligence import DecisionReport, DirectionalBias, EngineId, MarketRegime
from app.domain.knowledge import KnowledgeCategory, KnowledgeRecord, RelationshipRecord
from app.domain.market_data import DataProviderId, MarketSymbol, OhlcBar, Timeframe
from app.domain.notification_models import (
    ExpectedMove,
    InvalidationCondition,
    SupportResistanceLevels,
)
from app.domain.research import BacktestDecisionSample
from app.features.technical_features import build_technical_features
from app.infrastructure.repositories.json_knowledge_repository import JsonKnowledgeRepository
from app.reports.recommendation_report import RecommendationReportGenerator


def make_bars(count: int = 12) -> tuple[OhlcBar, ...]:
    start = datetime(2026, 7, 2, 0, 0, tzinfo=UTC)
    bars = []
    for index in range(count):
        close = Decimal("2300") + Decimal(index)
        bars.append(
            OhlcBar(
                symbol=MarketSymbol.XAU_USD,
                provider_symbol="XAU/USD",
                timeframe=Timeframe.ONE_HOUR,
                timestamp=start + timedelta(hours=index),
                open=close - Decimal("1"),
                high=close + Decimal("4"),
                low=close - Decimal("4"),
                close=close,
                provider=DataProviderId.TWELVE_DATA,
            )
        )
    return tuple(bars)


def make_decision(recommendation: Recommendation = Recommendation.WAIT) -> DecisionReport:
    now = datetime.now(UTC)
    evidence = (
        EvidenceRecord(
            evidence_id="E-1",
            category="Decision Discipline",
            description="WAIT is preferred until evidence clears thresholds.",
            strength=EvidenceStrength.HIGH,
            confidence=95,
            source="Decision Engine",
        ),
    )
    return DecisionReport(
        recommendation_id="REC-TEST",
        recommendation=recommendation,
        investment_score=55,
        opportunity_score=40,
        confidence=70,
        expected_move=ExpectedMove(direction="SIDEWAYS", summary="No action-quality move."),
        expected_holding_period="1-4 weeks",
        market_regime=MarketRegime.RANGE,
        supporting_evidence=evidence,
        risk_summary=(
            RiskRecord(
                risk="Synthetic test risk.",
                severity=EvidenceStrength.MEDIUM,
                probability=50,
            ),
        ),
        invalidation_conditions=(
            InvalidationCondition(condition="Fresh macro surprise requires reassessment."),
        ),
        support_resistance=SupportResistanceLevels(),
        explanation="Decision Engine recommends WAIT with incomplete evidence.",
        timestamp=now,
    )


def test_knowledge_base_records_and_relationships_round_trip(tmp_path):
    repository = JsonKnowledgeRepository(tmp_path / "knowledge")
    service = KnowledgeBaseService(repository, repository)
    record = KnowledgeRecord(
        record_id="macro-cpi-2026",
        category=KnowledgeCategory.MACRO_HISTORY,
        title="Soft CPI Supported Gold",
        body="A soft CPI print weakened the dollar and supported XAU/USD.",
        tags=("cpi", "dxy", "gold"),
    )
    relationship = RelationshipRecord(
        relationship_id="rel-dxy-gold",
        from_entity="DXY",
        relation="inverse_pressure",
        to_entity="Gold",
        strength=80,
        evidence_record_ids=(record.record_id,),
    )

    service.remember(record)
    service.connect(relationship)

    assert service.recall("soft cpi")[0].record_id == record.record_id
    assert service.relationships_for("Gold")[0].relationship_id == relationship.relationship_id


def test_ai_context_rag_and_json_validator(tmp_path):
    repository = JsonKnowledgeRepository(tmp_path / "knowledge")
    record = KnowledgeRecord(
        record_id="case-1",
        category=KnowledgeCategory.HISTORICAL_CASES,
        title="Dollar weakness case",
        body="Dollar weakness supported a gold rally.",
    )
    repository.upsert(record)
    context = AIContextBuilder().for_research_desk(_minimal_analysis_bundle())
    enriched = KnowledgeRetriever(repository).enrich(context, "Dollar weakness")

    class ExampleModel(BaseModel):
        score: int

    parsed, error = AIJsonValidator().validate('{"score": 88}', ExampleModel)

    assert enriched.retrieved_record_ids == ("case-1",)
    assert parsed is not None
    assert parsed.score == 88
    assert error is None


def test_event_bus_publishes_to_subscribers():
    bus = InMemoryEventBus()
    seen: list[DomainEvent] = []
    bus.subscribe(EventType.MARKET_UPDATED, seen.append)

    event = DomainEvent(event_id="evt-1", event_type=EventType.MARKET_UPDATED)
    bus.publish(event)

    assert seen == [event]
    assert bus.published_events == [event]


def test_feature_layer_feeds_technical_engine():
    features = build_technical_features(make_bars())
    analysis = TechnicalIntelligenceEngine().analyze_features(features)

    assert features.candle_count == 12
    assert features.latest_close == Decimal("2311")
    assert analysis.status == ContractStatus.SUCCESS
    assert analysis.engine == EngineId.TECHNICAL


def test_contract_registry_exports_json_schemas():
    schemas = export_contract_schemas()

    assert "decision_report" in schemas
    assert schemas["decision_report"]["title"] == "DecisionReport"


def test_recommendation_report_is_research_artifact():
    markdown = RecommendationReportGenerator().generate_markdown(make_decision())

    assert "# MIOS Recommendation Report" in markdown
    assert "Recommendation ID: REC-TEST" in markdown
    assert "Supporting Evidence" in markdown


def test_backtesting_replay_and_metrics_are_separate_boundaries():
    windows = HistoricalReplayer().windows(make_bars(10), lookback=5, horizon=2)
    samples = (
        BacktestDecisionSample(
            decision=make_decision(Recommendation.BUY),
            entry_price=Decimal("2300"),
            exit_price=Decimal("2310"),
            realized_move_usd=Decimal("10"),
            was_directionally_correct=True,
        ),
        BacktestDecisionSample(
            decision=make_decision(Recommendation.WAIT),
            entry_price=Decimal("2300"),
            exit_price=Decimal("2290"),
            realized_move_usd=Decimal("-10"),
            was_directionally_correct=True,
        ),
    )

    assert windows
    assert wait_count(samples) == 1
    assert directional_hit_rate(samples) == Decimal("100")


def _minimal_analysis_bundle():
    from app.domain.intelligence import (
        AnalysisBundle,
        FundamentalAnalysis,
        GeopoliticalAnalysis,
        InstitutionalAnalysis,
        MarketDataSnapshot,
        MarketRegimeAnalysis,
        NewsAnalysis,
        TechnicalAnalysis,
    )

    now = datetime.now(UTC)
    confidence = ConfidenceScore(value=70, reason="Test confidence.")
    evidence = (
        EvidenceRecord(
            evidence_id="TEST",
            category="Test",
            description="Synthetic evidence.",
            strength=EvidenceStrength.MEDIUM,
            confidence=70,
            source="Test",
        ),
    )
    return AnalysisBundle(
        market_data=MarketDataSnapshot(collected_at=now),
        technical=TechnicalAnalysis(
            engine=EngineId.TECHNICAL,
            status=ContractStatus.SUCCESS,
            confidence=confidence,
            quality=70,
            score=55,
            bias=DirectionalBias.NEUTRAL,
            evidence=evidence,
            trend_strength=50,
            momentum_score=50,
            volatility_score=30,
            support_resistance=SupportResistanceLevels(),
        ),
        fundamental=FundamentalAnalysis(
            engine=EngineId.FUNDAMENTAL,
            status=ContractStatus.SUCCESS,
            confidence=confidence,
            quality=70,
            score=55,
            bias=DirectionalBias.NEUTRAL,
            evidence=evidence,
            macro_narrative="Neutral macro.",
            dollar_bias=DirectionalBias.NEUTRAL,
            high_impact_event_count=0,
        ),
        news=NewsAnalysis(
            engine=EngineId.NEWS,
            status=ContractStatus.SUCCESS,
            confidence=confidence,
            quality=70,
            score=50,
            bias=DirectionalBias.NEUTRAL,
            evidence=evidence,
            analyzed_articles=0,
            high_severity_events=0,
        ),
        geopolitical=GeopoliticalAnalysis(
            engine=EngineId.GEOPOLITICAL,
            status=ContractStatus.SUCCESS,
            confidence=confidence,
            quality=70,
            score=50,
            bias=DirectionalBias.NEUTRAL,
            evidence=evidence,
            risk_score=40,
            conflict_status="Contained",
            expected_market_impact=DirectionalBias.NEUTRAL,
        ),
        institutional=InstitutionalAnalysis(
            engine=EngineId.INSTITUTIONAL,
            status=ContractStatus.SUCCESS,
            confidence=confidence,
            quality=70,
            score=50,
            bias=DirectionalBias.NEUTRAL,
            evidence=evidence,
            positioning_summary="Balanced.",
            etf_flow_score=50,
            cot_score=50,
        ),
        regime=MarketRegimeAnalysis(
            engine=EngineId.MARKET_REGIME,
            status=ContractStatus.SUCCESS,
            confidence=confidence,
            quality=70,
            score=50,
            bias=DirectionalBias.NEUTRAL,
            evidence=evidence,
            regime=MarketRegime.RANGE,
            dynamic_weights={
                EngineId.TECHNICAL: Decimal("0.25"),
                EngineId.FUNDAMENTAL: Decimal("0.25"),
                EngineId.MARKET_REGIME: Decimal("0.15"),
                EngineId.INSTITUTIONAL: Decimal("0.15"),
                EngineId.GEOPOLITICAL: Decimal("0.10"),
                EngineId.NEWS: Decimal("0.10"),
            },
        ),
    )
