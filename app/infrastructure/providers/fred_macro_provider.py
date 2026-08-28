from app.domain.common import ContractStatus, ProviderResult
from app.domain.market_data import DataProviderId, MacroSeriesObservation
from app.infrastructure.providers.base import ProviderBase, decimal_from_any, logger, parse_datetime


class FREDMacroProvider(ProviderBase):
    """Downloads FRED observations and only maps them into typed source records."""

    async def series_observations(
        self, series_id: str
    ) -> ProviderResult[tuple[MacroSeriesObservation, ...]]:
        status, payload, error = self._get_json(
            "series_observations",
            {"series_id": series_id, "file_type": "json", "sort_order": "asc"},
        )
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            observations = tuple(
                MacroSeriesObservation(
                    series_id=series_id,
                    date=parse_datetime(row["date"]),
                    value=decimal_from_any(row["value"]),
                    provider=DataProviderId.FRED,
                )
                for row in payload.get("observations", ())
                if row.get("value") not in (None, "", ".")
            )
            if not observations:
                return self._result(
                    ContractStatus.NO_DATA,
                    error=f"No usable FRED observations for {series_id}.",
                )
            return self._result(ContractStatus.SUCCESS, data=observations)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("%s parsing failed: %s", self.__class__.__name__, exc)
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
