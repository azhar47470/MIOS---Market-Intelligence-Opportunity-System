from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from app.domain.common import DomainModel


class COTSnapshot(DomainModel):
    long_positions: int = Field(ge=0)
    short_positions: int = Field(ge=0)
    net_position: int
    report_date: datetime

    @field_validator("report_date")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("report_date must be timezone-aware")
        return value


class ETFSnapshot(DomainModel):
    ounces: Decimal = Field(ge=Decimal("0"))
    flow_delta: Decimal | None = None
    total_tonnes: Decimal | None = Field(default=None, ge=Decimal("0"))
    total_nav_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    shares_outstanding: Decimal | None = Field(default=None, ge=Decimal("0"))
    field_dates: dict[str, datetime] = Field(default_factory=dict)
    date: datetime

    @field_validator("date")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("date must be timezone-aware")
        return value


class EconomicEventSnapshot(DomainModel):
    title: str = Field(min_length=1, max_length=180)
    time: datetime
    importance: str = Field(min_length=1, max_length=40)
    country: str = Field(min_length=1, max_length=80)
    actual: str | None = Field(default=None, max_length=80)
    forecast: str | None = Field(default=None, max_length=80)
    previous: str | None = Field(default=None, max_length=80)

    @field_validator("time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("time must be timezone-aware")
        return value


class NewsEventSnapshot(DomainModel):
    headline: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=1000)
    tone: Decimal | None = None
    date: datetime
    source: str | None = Field(default=None, max_length=120)

    @field_validator("date")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("date must be timezone-aware")
        return value


class DXYSnapshot(DomainModel):
    price: Decimal = Field(gt=Decimal("0"))
    change: Decimal | None = None
    previous_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    previous_timestamp: datetime | None = None
    timestamp: datetime

    @field_validator("timestamp", "previous_timestamp")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class GoldPriceSnapshot(DomainModel):
    price: Decimal = Field(gt=Decimal("0"))
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value
