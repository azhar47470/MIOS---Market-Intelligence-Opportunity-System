from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from app.domain.common import DomainModel, utc_now


class EventType(StrEnum):
    MARKET_UPDATED = "market_updated"
    MACRO_UPDATED = "macro_updated"
    COT_UPDATED = "cot_updated"
    ETF_UPDATED = "etf_updated"
    CALENDAR_UPDATED = "calendar_updated"
    NEWS_UPDATED = "news_updated"
    DXY_UPDATED = "dxy_updated"
    RECOMMENDATION_CHANGED = "recommendation_changed"
    SYSTEM_WARNING = "system_warning"


class EventPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class DomainEvent(DomainModel):
    event_id: str = Field(min_length=1, max_length=160)
    event_type: EventType
    priority: EventPriority = EventPriority.NORMAL
    occurred_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = Field(default=None, max_length=160)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamp must be timezone-aware")
        return value


class MarketUpdatedEvent(DomainEvent):
    event_type: EventType = EventType.MARKET_UPDATED


class MacroUpdatedEvent(DomainEvent):
    event_type: EventType = EventType.MACRO_UPDATED


class RecommendationChangedEvent(DomainEvent):
    event_type: EventType = EventType.RECOMMENDATION_CHANGED


class COTUpdatedEvent(DomainEvent):
    event_type: EventType = EventType.COT_UPDATED


class ETFUpdatedEvent(DomainEvent):
    event_type: EventType = EventType.ETF_UPDATED


class CalendarUpdatedEvent(DomainEvent):
    event_type: EventType = EventType.CALENDAR_UPDATED


class NewsUpdatedEvent(DomainEvent):
    event_type: EventType = EventType.NEWS_UPDATED


class DXYUpdatedEvent(DomainEvent):
    event_type: EventType = EventType.DXY_UPDATED
