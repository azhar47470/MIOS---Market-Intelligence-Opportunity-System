from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from app.domain.common import DomainModel


class DataProviderId(StrEnum):
    TWELVE_DATA = "twelve_data"
    FRED = "fred"
    NEWSAPI = "newsapi"
    GROQ = "groq"
    DISCORD = "discord"
    FINNHUB = "finnhub"
    GEMINI = "gemini"
    OPENCODE = "opencode"
    OLLAMA = "ollama"
    CFTC_COT = "cftc_cot"
    SPDR_GLD = "spdr_gld"
    GDELT = "gdelt"
    RSS_NEWS = "rss_news"
    GOLD_API = "gold_api"
    METALS_LIVE = "metals_live"
    YAHOO = "yahoo"


class MarketSymbol(StrEnum):
    XAU_USD = "XAU/USD"
    DXY = "DXY"
    US_10Y = "US10Y"


class Timeframe(StrEnum):
    ONE_MINUTE = "1min"
    FIVE_MINUTES = "5min"
    FIFTEEN_MINUTES = "15min"
    ONE_HOUR = "1h"
    FOUR_HOURS = "4h"
    ONE_DAY = "1day"


class MarketQuote(DomainModel):
    symbol: MarketSymbol
    provider_symbol: str = Field(min_length=1, max_length=80)
    price: Decimal = Field(gt=Decimal("0"))
    bid: Decimal | None = Field(default=None, gt=Decimal("0"))
    ask: Decimal | None = Field(default=None, gt=Decimal("0"))
    timestamp: datetime
    provider: DataProviderId

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value


class OhlcBar(DomainModel):
    symbol: MarketSymbol
    provider_symbol: str = Field(min_length=1, max_length=80)
    timeframe: Timeframe
    timestamp: datetime
    open: Decimal = Field(gt=Decimal("0"))
    high: Decimal = Field(gt=Decimal("0"))
    low: Decimal = Field(gt=Decimal("0"))
    close: Decimal = Field(gt=Decimal("0"))
    volume: Decimal | None = Field(default=None, ge=Decimal("0"))
    provider: DataProviderId

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_price_range(self) -> "OhlcBar":
        if self.low > self.high:
            raise ValueError("low cannot exceed high")
        if self.open > self.high or self.open < self.low:
            raise ValueError("open must be within high/low range")
        if self.close > self.high or self.close < self.low:
            raise ValueError("close must be within high/low range")
        return self


class MacroSeriesObservation(DomainModel):
    series_id: str = Field(min_length=1, max_length=80)
    date: datetime
    value: Decimal | None = None
    provider: DataProviderId

    @field_validator("date")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("date must be timezone-aware")
        return value


class EconomicCalendarEvent(DomainModel):
    event_id: str = Field(min_length=1, max_length=160)
    country: str = Field(min_length=1, max_length=80)
    event: str = Field(min_length=1, max_length=160)
    impact: str = Field(min_length=1, max_length=40)
    event_time: datetime
    actual: str | None = Field(default=None, max_length=80)
    forecast: str | None = Field(default=None, max_length=80)
    previous: str | None = Field(default=None, max_length=80)
    provider: DataProviderId

    @field_validator("event_time")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event_time must be timezone-aware")
        return value


class NewsArticle(DomainModel):
    article_id: str = Field(min_length=1, max_length=240)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=1000)
    source_name: str = Field(min_length=1, max_length=160)
    published_at: datetime
    summary: str | None = Field(default=None, max_length=1000)
    provider: DataProviderId

    @field_validator("published_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        return value


class CotPositioningSnapshot(DomainModel):
    report_date: datetime
    market_name: str = Field(min_length=1, max_length=240)
    managed_money_long: int = Field(ge=0)
    managed_money_short: int = Field(ge=0)
    managed_money_net: int
    provider: DataProviderId = DataProviderId.CFTC_COT

    @field_validator("report_date")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("report_date must be timezone-aware")
        return value


class EtfFlowSnapshot(DomainModel):
    date: datetime
    fund: str = Field(min_length=1, max_length=40)
    total_ounces: Decimal = Field(ge=Decimal("0"))
    daily_ounce_change: Decimal | None = None
    total_tonnes: Decimal | None = Field(default=None, ge=Decimal("0"))
    total_nav_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    shares_outstanding: Decimal | None = Field(default=None, ge=Decimal("0"))
    field_dates: dict[str, datetime] = Field(default_factory=dict)
    provider: DataProviderId = DataProviderId.SPDR_GLD

    @field_validator("date")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("date must be timezone-aware")
        return value

