from typing import Protocol

from app.domain.source_data import (
    CalendarSourceBundle,
    InstitutionalSourceBundle,
    MacroSourceBundle,
    MarketSourceBundle,
    NewsSourceBundle,
)


class InstitutionalRepository(Protocol):
    async def latest(self) -> InstitutionalSourceBundle:
        """Read latest institutional sources through cache-aware infrastructure."""


class CalendarRepository(Protocol):
    async def latest(self) -> CalendarSourceBundle:
        """Read latest economic calendar sources."""


class NewsEventRepository(Protocol):
    async def latest(self, query: str) -> NewsSourceBundle:
        """Read latest news/geopolitical sources."""


class MarketRepository(Protocol):
    async def latest(self) -> MarketSourceBundle:
        """Read latest price and cross-market sources."""


class MacroRepository(Protocol):
    async def latest(self) -> MacroSourceBundle:
        """Read configured macroeconomic time series."""
