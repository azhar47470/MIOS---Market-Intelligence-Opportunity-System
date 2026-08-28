from app.domain.common import ContractStatus, ProviderResult
from app.domain.market_data import MarketSymbol, OhlcBar, Timeframe
from app.infrastructure.providers.base import (
    ProviderBase,
    decimal_from_any,
    logger,
    optional_decimal,
    parse_datetime,
)


class TwelveDataProvider(ProviderBase):
    async def gold_ohlc(
        self, timeframe: Timeframe, output_size: int = 100
    ) -> ProviderResult[tuple[OhlcBar, ...]]:
        status, payload, error = self._get_json(
            "time_series",
            {
                "symbol": self._symbol(MarketSymbol.XAU_USD),
                "interval": timeframe.value,
                "outputsize": str(output_size),
            },
        )
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            bars = tuple(
                OhlcBar(
                    symbol=MarketSymbol.XAU_USD,
                    provider_symbol=self._symbol(MarketSymbol.XAU_USD),
                    timeframe=timeframe,
                    timestamp=parse_datetime(row["datetime"]),
                    open=decimal_from_any(row["open"]),
                    high=decimal_from_any(row["high"]),
                    low=decimal_from_any(row["low"]),
                    close=decimal_from_any(row["close"]),
                    volume=optional_decimal(row.get("volume")),
                    provider=self._config.provider_id,
                )
                for row in payload.get("values", ())
            )
            return self._result(
                ContractStatus.SUCCESS if bars else ContractStatus.NO_DATA, data=bars
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("%s parsing failed: %s", self.__class__.__name__, exc)
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
