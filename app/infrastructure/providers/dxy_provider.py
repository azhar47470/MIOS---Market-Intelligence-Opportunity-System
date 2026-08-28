from app.domain.common import ContractStatus, ProviderResult
from app.domain.provider_snapshots import DXYSnapshot
from app.infrastructure.providers.base import ProviderBase, decimal_from_any, logger, parse_datetime


class DXYProvider:
    """DXY comes from FRED's Trade Weighted Dollar Index only.

    TwelveData's DXY quote endpoint was dropped (Task 3): it consistently returned
    "404 invalid symbol" and added no value once the FRED fallback below covers every
    case. Note this is a different instrument, not a live substitute — FRED's
    ``DTWEXBGS`` is a broader, differently-weighted basket than the six-currency ICE
    Dollar Index, published once a business day (roughly a one-day lag), not tick by
    tick. That's fine for macro-context confidence scoring; it's why this provider is
    cached at a daily TTL rather than the 30-second TTL a live quote would use.

    TwelveData remains the *gold* price provider (``TwelveDataProvider.gold_ohlc``) —
    that relationship is untouched by this class.
    """

    def __init__(self, fred_provider: ProviderBase | None) -> None:
        self._fred_provider = fred_provider

    async def latest_dxy(self) -> ProviderResult[DXYSnapshot]:
        if self._fred_provider is None:
            logger.warning(
                "%s parsing failed: %s",
                self.__class__.__name__,
                "No DXY provider available.",
            )
            return ProviderResult(
                status=ContractStatus.NO_DATA,
                provider="dxy",
                data=None,
                error="No DXY provider available.",
            )
        status, payload, error = self._fred_provider._get_json(
            "series_observations",
            {"series_id": "DTWEXBGS", "file_type": "json"},
        )
        if status != ContractStatus.SUCCESS:
            return self._fred_provider._result(status, error=error)
        try:
            observations = [
                row
                for row in payload.get("observations", ())
                if row.get("value") not in (None, "", ".")
            ]
            if len(observations) < 1:
                logger.warning("%s parsing failed: %s", self.__class__.__name__, "No DXY rows.")
                return self._fred_provider._result(ContractStatus.NO_DATA, error="No DXY rows.")
            latest = observations[-1]
            previous = observations[-2] if len(observations) >= 2 else None
            price = decimal_from_any(latest["value"])
            previous_price = decimal_from_any(previous["value"]) if previous else None
            previous_timestamp = parse_datetime(previous["date"]) if previous else None
            return self._fred_provider._result(
                ContractStatus.SUCCESS,
                data=DXYSnapshot(
                    price=price,
                    change=price - previous_price if previous_price is not None else None,
                    previous_price=previous_price,
                    previous_timestamp=previous_timestamp,
                    timestamp=parse_datetime(latest["date"]),
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("%s parsing failed: %s", self.__class__.__name__, exc)
            return self._fred_provider._result(ContractStatus.INVALID_INPUT, error=str(exc))
