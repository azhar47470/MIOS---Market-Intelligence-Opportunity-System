from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from app.domain.common import DomainModel


class TechnicalSignalDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class StructureSignal(DomainModel):
    signal_type: str = Field(min_length=1, max_length=20)
    direction: TechnicalSignalDirection
    broken_level: Decimal
    close: Decimal


class SwingPoint(DomainModel):
    candle_index: int = Field(ge=0)
    price: Decimal


class LiquiditySweep(DomainModel):
    direction: TechnicalSignalDirection
    swept_level: Decimal
    close: Decimal


class PremiumDiscountZone(DomainModel):
    range_low: Decimal
    equilibrium: Decimal
    range_high: Decimal
    current_zone: str = Field(min_length=1, max_length=20)


class FairValueGap(DomainModel):
    direction: TechnicalSignalDirection
    lower_bound: Decimal
    upper_bound: Decimal


class OrderBlock(DomainModel):
    direction: TechnicalSignalDirection
    low: Decimal
    high: Decimal
    block_type: str = Field(default="ORDER_BLOCK", min_length=1, max_length=40)
    mitigated: bool = False


class AsianRangeSignal(DomainModel):
    high: Decimal
    low: Decimal
    breakout_direction: TechnicalSignalDirection = TechnicalSignalDirection.NEUTRAL


from datetime import datetime

class TechnicalFeatureSet(DomainModel):
    candle_count: int = Field(ge=0)
    latest_timestamp: datetime | None = None
    latest_close: Decimal | None = None
    rsi_14: Decimal | None = None
    ema_200: Decimal | None = None
    daily_trend: TechnicalSignalDirection | None = None
    short_moving_average: Decimal | None = None
    long_moving_average: Decimal | None = None
    average_true_range: Decimal | None = None
    momentum_percent: Decimal | None = None
    support: Decimal | None = None
    resistance: Decimal | None = None
    structure_signal: StructureSignal | None = None
    swing_highs: tuple[SwingPoint, ...] = Field(default_factory=tuple)
    swing_lows: tuple[SwingPoint, ...] = Field(default_factory=tuple)
    liquidity_sweep: LiquiditySweep | None = None
    premium_discount: PremiumDiscountZone | None = None
    fair_value_gaps: tuple[FairValueGap, ...] = Field(default_factory=tuple)
    order_block: OrderBlock | None = None
    breaker_block: OrderBlock | None = None
    mitigation_block: OrderBlock | None = None
    asian_range: AsianRangeSignal | None = None
    vwap: Decimal | None = None
    volume_ratio: Decimal | None = None
    volume_confirmation: TechnicalSignalDirection = TechnicalSignalDirection.NEUTRAL
    volatility_regime: str = Field(default="UNKNOWN", min_length=1, max_length=40)
    trend_quality: int = Field(default=0, ge=0, le=100)
    support_confidence: int = Field(default=0, ge=0, le=100)
    resistance_confidence: int = Field(default=0, ge=0, le=100)
    timeframe_biases: dict[str, TechnicalSignalDirection] = Field(default_factory=dict)
    multi_timeframe_aligned: bool = False
    higher_timeframe_confirmed: bool = False
    market_structure_shift: bool = False


class MacroSeriesFeature(DomainModel):
    observation_count: int = Field(ge=0)
    latest_value: Decimal | None = None
    change_percent: Decimal | None = None


class MacroFeatureSet(DomainModel):
    observation_count: int = Field(ge=0)
    dxy_change_percent: Decimal | None = None
    high_impact_us_event_count: int = Field(ge=0)
    macro_series: dict[str, MacroSeriesFeature] = Field(default_factory=dict)
    macro_surprise_count: int = Field(default=0, ge=0)
    dxy_error: str | None = Field(default=None, max_length=1000)
    macro_error: str | None = Field(default=None, max_length=1000)


class ArticleCluster(DomainModel):
    cluster_id: str = Field(min_length=1, max_length=120)
    narrative: str = Field(min_length=1, max_length=120)
    article_count: int = Field(ge=1)
    representative_headline: str = Field(min_length=1, max_length=500)
    topics: tuple[str, ...] = Field(default_factory=tuple)


class ArticleIntelligenceFeatureSet(DomainModel):
    source_article_count: int = Field(ge=0)
    unique_article_count: int = Field(ge=0)
    duplicate_article_count: int = Field(ge=0)
    clusters: tuple[ArticleCluster, ...] = Field(default_factory=tuple)
    entities: tuple[str, ...] = Field(default_factory=tuple)
    countries: tuple[str, ...] = Field(default_factory=tuple)
    institutions: tuple[str, ...] = Field(default_factory=tuple)
    average_gold_relevance: int = Field(default=0, ge=0, le=100)
    estimated_duration_hours: int = Field(default=0, ge=0, le=720)
    high_relevance_article_count: int = Field(default=0, ge=0)


class InstitutionalFeatureSet(DomainModel):
    source_count: int = Field(ge=0)
    latest_managed_money_net: int | None = None
    gld_daily_ounce_change: Decimal | None = None
    gld_total_ounces: Decimal | None = None
    gld_total_tonnes: Decimal | None = None
    gld_total_nav_usd: Decimal | None = None
    gld_shares_outstanding: Decimal | None = None
    gld_date: str | None = Field(default=None, max_length=80)
    cot_error: str | None = Field(default=None, max_length=1000)
    gld_error: str | None = Field(default=None, max_length=1000)
