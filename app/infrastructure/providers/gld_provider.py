from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.common import ContractStatus, ProviderResult
from app.domain.provider_snapshots import ETFSnapshot
from app.infrastructure.providers.base import ProviderBase, logger, parse_datetime


class GLDProvider(ProviderBase):
    async def latest_flow(self) -> ProviderResult[ETFSnapshot]:
        status, payload, error = self._get_json("gld_data")
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            data = payload["data"]
            system = payload.get("system", {})
            fallback_date = _parse_response_time(system.get("request_time"))
            total_ounces_value, total_ounces_date = _field_value_and_date(
                data, "total_ounces", fallback_date
            )
            total_tonnes_value, total_tonnes_date = _field_value_and_date(
                data, "total_tonnes", fallback_date
            )
            total_nav_value, total_nav_date = _field_value_and_date(
                data, "total_nav_usd", fallback_date
            )
            shares_value, shares_date = _field_value_and_date(
                data, "shares_outstanding", fallback_date
            )
            return self._result(
                ContractStatus.SUCCESS,
                data=ETFSnapshot(
                    ounces=total_ounces_value,
                    flow_delta=None,
                    date=total_ounces_date,
                    total_tonnes=total_tonnes_value,
                    total_nav_usd=total_nav_value,
                    shares_outstanding=shares_value,
                    field_dates={
                        "total_ounces": total_ounces_date,
                        "total_tonnes": total_tonnes_date,
                        "total_nav_usd": total_nav_date,
                        "shares_outstanding": shares_date,
                    },
                ),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            logger.warning("%s parsing failed: %s", self.__class__.__name__, exc)
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))


def _field_value_and_date(
    data: dict[str, Any], field_name: str, fallback_date: datetime
) -> tuple[Decimal, datetime]:
    if field_name not in data:
        raise KeyError(f"Missing GLD field: {field_name}")
    field = data[field_name]
    raw_value = field.get("value")
    field_date = _parse_field_date(field.get("date")) if field.get("date") else fallback_date
    return _parse_money_or_number(raw_value), field_date


def _parse_money_or_number(raw: str) -> Decimal:
    if raw in (None, ""):
        raise ValueError("missing numeric value")
    normalized = str(raw).replace("US$", "").replace(",", "").strip()
    if normalized in ("", "N/A", "."):
        raise ValueError(f"invalid numeric value: {raw}")
    return Decimal(normalized)


def _parse_field_date(raw: Any) -> datetime:
    parsed = datetime.strptime(str(raw), "%B %d, %Y")
    return parsed.replace(tzinfo=UTC)


def _parse_response_time(raw: Any) -> datetime:
    if raw:
        return parse_datetime(raw)
    return datetime.now(UTC)
