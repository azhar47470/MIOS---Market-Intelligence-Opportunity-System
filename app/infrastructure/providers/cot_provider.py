from app.domain.common import ContractStatus, ProviderResult
from app.domain.provider_snapshots import COTSnapshot
from app.infrastructure.providers.base import ProviderBase, logger, parse_datetime


class COTProvider(ProviderBase):
    async def latest_gold_positions(self) -> ProviderResult[COTSnapshot]:
        status, payload, error = self._get_json(
            "cot_disaggregated",
            {
                "$where": "market_and_exchange_names = 'GOLD - COMMODITY EXCHANGE INC.'",
                "$order": "report_date_as_yyyy_mm_dd DESC",
                "$limit": "1",
            },
        )
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            if not payload:
                logger.warning(
                    "%s parsing failed: %s",
                    self.__class__.__name__,
                    "No GOLD rows found in COT data.",
                )
                return self._result(ContractStatus.NO_DATA, error="No GOLD rows found in COT data.")
            latest = payload[0]
            long_positions = int(latest["m_money_positions_long_all"])
            short_positions = int(latest["m_money_positions_short_all"])
            return self._result(
                ContractStatus.SUCCESS,
                data=COTSnapshot(
                    long_positions=long_positions,
                    short_positions=short_positions,
                    net_position=long_positions - short_positions,
                    report_date=parse_datetime(latest["report_date_as_yyyy_mm_dd"]),
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("%s parsing failed: %s", self.__class__.__name__, exc)
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
