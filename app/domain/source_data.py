from pydantic import Field

from app.domain.common import ContractStatus, DomainModel
from app.domain.market_data import MacroSeriesObservation, OhlcBar
from app.domain.provider_snapshots import (
    COTSnapshot,
    DXYSnapshot,
    EconomicEventSnapshot,
    ETFSnapshot,
    GoldPriceSnapshot,
    NewsEventSnapshot,
)


class SourceReadResult[T](DomainModel):
    status: ContractStatus
    data: T | None = None
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    used_cache: bool = False
    confidence_penalty: int = Field(default=0, ge=0, le=100)
    error: str | None = Field(default=None, max_length=1000)


class InstitutionalSourceBundle(DomainModel):
    cot: SourceReadResult[COTSnapshot]
    gld: SourceReadResult[ETFSnapshot]


class CalendarSourceBundle(DomainModel):
    events: SourceReadResult[tuple[EconomicEventSnapshot, ...]]


class NewsSourceBundle(DomainModel):
    events: SourceReadResult[tuple[NewsEventSnapshot, ...]]


class MarketSourceBundle(DomainModel):
    gold_price: SourceReadResult[GoldPriceSnapshot]
    gold_bars: SourceReadResult[tuple[OhlcBar, ...]]
    dxy: SourceReadResult[DXYSnapshot]


class MacroSourceBundle(DomainModel):
    observations: SourceReadResult[tuple[MacroSeriesObservation, ...]]
