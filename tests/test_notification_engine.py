from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.application.notification_config import NotificationConfig
from app.application.notification_engine import NotificationEngine
from app.domain.enums import (
    DeliveryStatus,
    MarketEventKind,
    NotificationKind,
    NotificationPriority,
    Recommendation,
)
from app.domain.notification_models import (
    DeliveryReceipt,
    EvidenceItem,
    ExpectedMove,
    InvalidationCondition,
    MarketEventImpact,
    PriceLevel,
    RecommendationSnapshot,
    RiskItem,
    StructuredNotification,
    SupportResistanceLevels,
)
from app.infrastructure.repositories.memory_notification_state_repository import (
    MemoryNotificationStateRepository,
)


class FakeClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current = self.current + timedelta(seconds=seconds)


class FakePublisher:
    def __init__(self) -> None:
        self.messages = []

    def publish(self, message):
        self.messages.append(message)
        return DeliveryReceipt(status=DeliveryStatus.SENT, detail="sent")


def make_snapshot(
    recommendation: Recommendation = Recommendation.WAIT,
    confidence: int = 82,
    recommendation_id: str = "REC-1",
) -> RecommendationSnapshot:
    return RecommendationSnapshot(
        recommendation_id=recommendation_id,
        recommendation=recommendation,
        investment_score=71,
        confidence=confidence,
        expected_move=ExpectedMove(
            direction="UP",
            min_usd=Decimal("30"),
            max_usd=Decimal("50"),
            summary="Upside favored if real yields continue easing.",
        ),
        expected_holding_period="2-5 days",
        market_regime="Event-Driven Bullish",
        supporting_evidence=(
            EvidenceItem(
                category="Macro",
                description="Real yields weakened while dollar momentum faded.",
                strength="HIGH",
                confidence=88,
                source="Fundamental Engine",
            ),
        ),
        risk_summary=(
            RiskItem(
                summary="Upcoming inflation release may reverse the move.",
                severity=NotificationPriority.HIGH,
                probability=62,
            ),
        ),
        invalidation_conditions=(
            InvalidationCondition(
                condition="Daily close below primary support.",
                severity=NotificationPriority.HIGH,
            ),
        ),
        support_resistance=SupportResistanceLevels(
            support=(PriceLevel(label="S1", price=Decimal("2320")),),
            resistance=(PriceLevel(label="R1", price=Decimal("2385")),),
        ),
        timestamp=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
    )


def build_engine(config: NotificationConfig | None = None):
    publisher = FakePublisher()
    repository = MemoryNotificationStateRepository()
    clock = FakeClock(datetime(2026, 7, 2, 12, 0, tzinfo=UTC))
    engine = NotificationEngine(
        publisher=publisher,
        state_repository=repository,
        config=config or NotificationConfig(),
        clock=clock,
    )
    return engine, publisher, repository, clock


def test_expected_move_serializes_usd_values_to_two_decimal_places():
    move = ExpectedMove(
        direction="UP",
        min_usd=Decimal("150") / Decimal("7"),
        max_usd=Decimal("225") / Decimal("7"),
        summary="Repeating decimals should not leak into reports.",
    )

    payload = move.model_dump(mode="json")

    assert payload["min_usd"] == "21.43"
    assert payload["max_usd"] == "32.14"


def test_initial_snapshot_records_baseline_without_sending_by_default():
    engine, publisher, repository, _clock = build_engine()

    outcome = engine.process_recommendation(make_snapshot())

    assert outcome.status is DeliveryStatus.SUPPRESSED
    assert len(publisher.messages) == 0
    assert repository.state.last_evaluated_recommendation is not None


def test_recommendation_change_sends_discord_embed():
    engine, publisher, _repository, _clock = build_engine()
    engine.process_recommendation(make_snapshot(Recommendation.WAIT, 82, "REC-1"))

    outcome = engine.process_recommendation(make_snapshot(Recommendation.BUY, 86, "REC-2"))

    assert outcome.status is DeliveryStatus.SENT
    assert len(publisher.messages) == 1
    embed = publisher.messages[0].embeds[0]
    field_names = {field.name for field in embed.fields}
    assert {
        "Recommendation",
        "Investment Score",
        "Confidence",
        "Expected Move",
        "Expected Holding Period",
        "Market Regime",
        "Supporting Evidence",
        "Risk Summary",
        "Invalidation Conditions",
        "Support & Resistance Levels",
        "Timestamp",
    }.issubset(field_names)


def test_small_confidence_change_is_suppressed():
    engine, publisher, _repository, _clock = build_engine()
    engine.process_recommendation(make_snapshot(Recommendation.WAIT, 82, "REC-1"))

    outcome = engine.process_recommendation(make_snapshot(Recommendation.WAIT, 86, "REC-2"))

    assert outcome.status is DeliveryStatus.SUPPRESSED
    assert len(publisher.messages) == 0


def test_significant_confidence_change_sends_once_then_consolidates_inside_window():
    config = NotificationConfig()
    engine, publisher, _repository, clock = build_engine(config)
    engine.process_recommendation(make_snapshot(Recommendation.WAIT, 70, "REC-1"))
    first = engine.process_recommendation(make_snapshot(Recommendation.WAIT, 82, "REC-2"))

    assert first.status is DeliveryStatus.SENT
    assert len(publisher.messages) == 1

    clock.advance(60)
    second = engine.process_recommendation(make_snapshot(Recommendation.WAIT, 92, "REC-3"))

    assert second.status is DeliveryStatus.CONSOLIDATED
    assert len(publisher.messages) == 1

    clock.advance(config.alert_rules.consolidation_window_seconds)
    flushed = engine.flush_pending_updates()

    assert flushed.status is DeliveryStatus.SENT
    assert len(publisher.messages) == 2


def test_major_events_and_high_priority_risks_send_alerts():
    engine, publisher, _repository, _clock = build_engine()
    engine.process_recommendation(make_snapshot(Recommendation.WAIT, 82, "REC-1"))
    event = MarketEventImpact(
        kind=MarketEventKind.MACROECONOMIC,
        title="High-impact inflation surprise",
        summary="Actual inflation materially missed expectations.",
        materiality_score=91,
        priority=NotificationPriority.HIGH,
        timestamp=datetime(2026, 7, 2, 12, 1, tzinfo=UTC),
    )

    outcome = engine.process_recommendation(
        make_snapshot(Recommendation.WAIT, 83, "REC-2"),
        events=(event,),
    )

    assert outcome.status is DeliveryStatus.SENT
    assert len(publisher.messages) == 1


def test_structured_notification_supports_required_report_types():
    engine, publisher, _repository, _clock = build_engine()

    for kind in (
        NotificationKind.DAILY_MARKET_SUMMARY,
        NotificationKind.WEEKLY_INTELLIGENCE_REPORT,
        NotificationKind.BREAKING_NEWS_ALERT,
        NotificationKind.MAJOR_ECONOMIC_EVENT_ALERT,
        NotificationKind.SYSTEM_HEALTH_NOTIFICATION,
        NotificationKind.ENGINE_STATUS_NOTIFICATION,
    ):
        outcome = engine.send_structured_notification(
            StructuredNotification(
                kind=kind,
                title=kind.value,
                summary="Market intelligence update.",
                priority=NotificationPriority.NORMAL,
            )
        )
        assert outcome.status is DeliveryStatus.SENT

    assert len(publisher.messages) == 6
