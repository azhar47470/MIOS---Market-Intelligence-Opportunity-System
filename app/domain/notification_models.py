from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import (
    AlertTrigger,
    DeliveryStatus,
    MarketEventKind,
    NotificationKind,
    NotificationPriority,
    Recommendation,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=False)


class EvidenceItem(DomainModel):
    category: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    strength: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    confidence: int = Field(ge=0, le=100)
    source: str = Field(min_length=1, max_length=120)


class RiskItem(DomainModel):
    summary: str = Field(min_length=1, max_length=500)
    severity: NotificationPriority
    probability: int = Field(ge=0, le=100)


class InvalidationCondition(DomainModel):
    condition: str = Field(min_length=1, max_length=500)
    severity: NotificationPriority = NotificationPriority.NORMAL


class PriceLevel(DomainModel):
    label: str = Field(min_length=1, max_length=80)
    price: Decimal = Field(gt=Decimal("0"))
    rationale: str | None = Field(default=None, max_length=300)


class SupportResistanceLevels(DomainModel):
    support: tuple[PriceLevel, ...] = Field(default_factory=tuple)
    resistance: tuple[PriceLevel, ...] = Field(default_factory=tuple)


class ExpectedMove(DomainModel):
    direction: Literal["UP", "DOWN", "SIDEWAYS", "MIXED"]
    min_usd: Decimal | None = None
    max_usd: Decimal | None = None
    summary: str = Field(min_length=1, max_length=300)

    @field_validator("min_usd", "max_usd")
    @classmethod
    def quantize_usd(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(Decimal("0.01"))

    @model_validator(mode="after")
    def validate_move_range(self) -> "ExpectedMove":
        if self.min_usd is not None and self.min_usd < 0:
            raise ValueError("min_usd must be non-negative")
        if self.max_usd is not None and self.max_usd < 0:
            raise ValueError("max_usd must be non-negative")
        if self.min_usd is not None and self.max_usd is not None and self.min_usd > self.max_usd:
            raise ValueError("min_usd cannot exceed max_usd")
        return self


class RecommendationSnapshot(DomainModel):
    recommendation_id: str = Field(min_length=1, max_length=120)
    recommendation: Recommendation
    investment_score: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    expected_move: ExpectedMove
    expected_holding_period: str = Field(min_length=1, max_length=80)
    market_regime: str = Field(min_length=1, max_length=120)
    supporting_evidence: tuple[EvidenceItem, ...] = Field(min_length=1)
    contradicting_evidence: tuple[EvidenceItem, ...] = Field(default_factory=tuple)
    risk_summary: tuple[RiskItem, ...] = Field(min_length=1)
    invalidation_conditions: tuple[InvalidationCondition, ...] = Field(min_length=1)
    support_resistance: SupportResistanceLevels
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class MarketEventImpact(DomainModel):
    kind: MarketEventKind
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=600)
    materiality_score: int = Field(ge=0, le=100)
    priority: NotificationPriority = NotificationPriority.NORMAL
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class NotificationField(DomainModel):
    name: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=1500)
    inline: bool = False


class StructuredNotification(DomainModel):
    kind: NotificationKind
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1500)
    priority: NotificationPriority = NotificationPriority.NORMAL
    fields: tuple[NotificationField, ...] = Field(default_factory=tuple)
    timestamp: datetime = Field(default_factory=utc_now)

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class DiscordEmbedField(DomainModel):
    name: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=1024)
    inline: bool = False


class DiscordEmbedFooter(DomainModel):
    text: str = Field(min_length=1, max_length=2048)


class DiscordEmbed(DomainModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4096)
    color: int = Field(ge=0, le=0xFFFFFF)
    fields: tuple[DiscordEmbedField, ...] = Field(default_factory=tuple, max_length=25)
    timestamp: datetime
    footer: DiscordEmbedFooter | None = None


class DiscordMessage(DomainModel):
    username: str = Field(default="Gold Intelligence Platform", min_length=1, max_length=80)
    avatar_url: str | None = None
    embeds: tuple[DiscordEmbed, ...] = Field(min_length=1, max_length=10)


class PendingAlert(DomainModel):
    trigger: AlertTrigger
    reason: str = Field(min_length=1, max_length=500)
    snapshot: RecommendationSnapshot
    events: tuple[MarketEventImpact, ...] = Field(default_factory=tuple)
    queued_at: datetime = Field(default_factory=utc_now)


class NotificationState(DomainModel):
    last_evaluated_recommendation: RecommendationSnapshot | None = None
    last_notified_recommendation: RecommendationSnapshot | None = None
    last_alert_at: datetime | None = None
    pending_alerts: tuple[PendingAlert, ...] = Field(default_factory=tuple)


class DeliveryReceipt(DomainModel):
    status: DeliveryStatus
    provider_message_id: str | None = None
    detail: str | None = None
    delivered_at: datetime = Field(default_factory=utc_now)


class NotificationOutcome(DomainModel):
    status: DeliveryStatus
    trigger: AlertTrigger | None = None
    reason: str
    receipt: DeliveryReceipt | None = None
    pending_count: int = 0
