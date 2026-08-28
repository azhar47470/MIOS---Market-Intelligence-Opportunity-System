from app.domain.common import ContractStatus, ProviderResult
from app.domain.provider_snapshots import EconomicEventSnapshot
from app.infrastructure.providers.base import ProviderBase, logger, parse_datetime

RELEVANT_RELEASE_IDS = {
    "10",  # Consumer Price Index
    "11",  # Employment Cost Index
    "13",  # G.17 Industrial Production and Capacity Utilization
    "46",  # Producer Price Index
    "50",  # Employment Situation
    "53",  # Gross Domestic Product
    "54",  # Personal Income and Outlays
    "92",  # Selected Real Retail Sales Series
    "101",  # FOMC Press Release
}


class FREDCalendarProvider(ProviderBase):
    async def upcoming_releases(self) -> ProviderResult[tuple[EconomicEventSnapshot, ...]]:
        status, payload, error = self._get_json(
            "releases_dates",
            {
                "file_type": "json",
                "include_release_dates_with_no_data": "true",
                "limit": "1000",
                "sort_order": "desc",
            },
        )
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            events = tuple(
                EconomicEventSnapshot(
                    title=str(row["release_name"]),
                    time=parse_datetime(row["date"]),
                    importance="unrated",
                    country="US",
                )
                for row in payload.get("release_dates", ())
                if str(row.get("release_id")) in RELEVANT_RELEASE_IDS
            )
            if not events:
                logger.warning(
                    "%s parsing failed: %s",
                    self.__class__.__name__,
                    "No relevant FRED release dates found.",
                )
                return self._result(
                    ContractStatus.NO_DATA,
                    error="No relevant FRED release dates found.",
                )
            return self._result(ContractStatus.SUCCESS, data=events)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("%s parsing failed: %s", self.__class__.__name__, exc)
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
