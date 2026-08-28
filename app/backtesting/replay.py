from pydantic import Field

from app.domain.common import DomainModel
from app.domain.market_data import OhlcBar


class ReplayWindow(DomainModel):
    lookback_bars: tuple[OhlcBar, ...] = Field(min_length=1)
    future_bars: tuple[OhlcBar, ...] = Field(min_length=1)


class HistoricalReplayer:
    def windows(
        self,
        bars: tuple[OhlcBar, ...],
        lookback: int,
        horizon: int,
    ) -> tuple[ReplayWindow, ...]:
        ordered = tuple(sorted(bars, key=lambda bar: bar.timestamp))
        if len(ordered) <= lookback + horizon:
            return ()
        return tuple(
            ReplayWindow(
                lookback_bars=ordered[index - lookback : index],
                future_bars=ordered[index : index + horizon],
            )
            for index in range(lookback, len(ordered) - horizon + 1)
        )
