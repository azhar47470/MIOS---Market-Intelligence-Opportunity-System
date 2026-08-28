from datetime import UTC, datetime
from decimal import Decimal

from app.application.discord_embed_formatter import DiscordEmbedFormatter
from app.application.notification_config import NotificationConfig
from app.domain.enums import AlertTrigger, NotificationPriority, Recommendation
from app.domain.notification_models import (
    EvidenceItem,
    ExpectedMove,
    InvalidationCondition,
    PriceLevel,
    RecommendationSnapshot,
    RiskItem,
    SupportResistanceLevels,
)


def _snapshot_with_long_evidence(item_count: int) -> RecommendationSnapshot:
    long_description = "A" * 480  # near EvidenceItem's own 500-char max
    evidence = tuple(
        EvidenceItem(
            category=f"Category {index}",
            description=long_description,
            strength="MEDIUM",
            confidence=70,
            source="Test Engine",
        )
        for index in range(item_count)
    )
    return RecommendationSnapshot(
        recommendation_id="REC-TEST-0001",
        recommendation=Recommendation.WAIT,
        investment_score=52,
        confidence=57,
        expected_move=ExpectedMove(direction="SIDEWAYS", summary="No action-quality move."),
        expected_holding_period="1-4 weeks",
        market_regime="LOW_VOLATILITY",
        supporting_evidence=evidence,
        risk_summary=(
            RiskItem(
                summary="Placeholder risk.",
                severity=NotificationPriority.NORMAL,
                probability=50,
            ),
        ),
        invalidation_conditions=(
            InvalidationCondition(condition="Placeholder invalidation."),
        ),
        support_resistance=SupportResistanceLevels(
            support=(PriceLevel(label="S1", price=Decimal("4010.47")),),
            resistance=(PriceLevel(label="R1", price=Decimal("4010.72")),),
        ),
        timestamp=datetime(2026, 7, 19, 8, 38, tzinfo=UTC),
    )


def test_truncate_never_exceeds_the_requested_limit():
    formatter = DiscordEmbedFormatter(NotificationConfig())

    result = formatter._truncate("x" * 2000, 1024)

    assert len(result) == 1024
    assert result.endswith("...")


def test_truncate_leaves_short_values_untouched():
    formatter = DiscordEmbedFormatter(NotificationConfig())

    result = formatter._truncate("short value", 1024)

    assert result == "short value"


def test_format_recommendation_does_not_crash_with_many_long_evidence_items():
    # 10 items x ~500 chars each comfortably exceeds Discord's 1024-char field limit,
    # reproducing the real crash: pydantic rejected the untruncated/mis-truncated value.
    formatter = DiscordEmbedFormatter(NotificationConfig())
    snapshot = _snapshot_with_long_evidence(item_count=10)

    message = formatter.format_recommendation(
        snapshot=snapshot,
        trigger=AlertTrigger.INITIAL_SNAPSHOT,
        reason="Test reason for a decision that includes plenty of supporting evidence.",
    )

    for field in message.embeds[0].fields:
        assert len(field.value) <= 1024
