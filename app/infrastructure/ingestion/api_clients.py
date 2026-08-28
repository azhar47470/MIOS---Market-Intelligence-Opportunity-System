import hashlib
import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.application.http import HttpClient
from app.application.platform_config import ApiProviderConfig, AuthMode, EndpointConfig
from app.domain.common import ContractMetadata, ContractStatus, DataQuality, ProviderResult
from app.domain.market_data import (
    CotPositioningSnapshot,
    DataProviderId,
    EtfFlowSnapshot,
    MacroSeriesObservation,
    MarketQuote,
    MarketSymbol,
    NewsArticle,
    OhlcBar,
    Timeframe,
)
from app.infrastructure.providers.base import BROWSER_USER_AGENT


class BaseApiClient:
    def __init__(self, config: ApiProviderConfig, http_client: HttpClient) -> None:
        self._config = config
        self._http_client = http_client

    @property
    def provider_id(self) -> DataProviderId:
        return self._config.provider_id

    def _endpoint(self, name: str) -> EndpointConfig:
        return self._config.endpoints[name]

    def _url(self, endpoint_name: str) -> str:
        path = self._endpoint(endpoint_name).path
        if path.startswith("http"):
            return path
        return f"{self._config.base_url}{path}"

    def _endpoint_params(self, endpoint_name: str) -> dict[str, str]:
        return dict(self._endpoint(endpoint_name).query_params)

    def _auth_params(self) -> dict[str, str]:
        if self._config.auth_mode != AuthMode.QUERY_PARAM:
            return {}
        if not self._config.api_key_env or not self._config.api_key_param:
            return {}
        api_key = os.getenv(self._config.api_key_env)
        if not api_key:
            return {}
        return {self._config.api_key_param: api_key}

    def _missing_secret_error(self) -> str | None:
        if self._config.auth_mode == AuthMode.NONE or not self._config.api_key_env:
            return None
        if os.getenv(self._config.api_key_env):
            return None
        return f"Required environment variable {self._config.api_key_env} is not set."

    def _get_json(
        self,
        endpoint_name: str,
        params: dict[str, str] | None = None,
    ) -> tuple[ContractStatus, Any, str | None]:
        secret_error = self._missing_secret_error()
        if secret_error:
            return ContractStatus.FAILED, None, secret_error

        request_params = {
            **self._endpoint_params(endpoint_name),
            **(params or {}),
            **self._auth_params(),
        }
        response = self._http_client.get(
            self._url(endpoint_name),
            params=request_params,
            headers={"User-Agent": BROWSER_USER_AGENT},
            timeout_seconds=self._config.timeout_seconds,
        )
        if response.status_code >= 400:
            return ContractStatus.FAILED, None, response.body
        try:
            return ContractStatus.SUCCESS, json.loads(response.body), None
        except json.JSONDecodeError as error:
            return ContractStatus.INVALID_INPUT, None, str(error)

    def _get_text(
        self,
        endpoint_name: str,
        params: dict[str, str] | None = None,
    ) -> tuple[ContractStatus, str | None, str | None]:
        secret_error = self._missing_secret_error()
        if secret_error:
            return ContractStatus.FAILED, None, secret_error

        response = self._http_client.get(
            self._url(endpoint_name),
            params={
                **self._endpoint_params(endpoint_name),
                **(params or {}),
                **self._auth_params(),
            },
            headers={"User-Agent": BROWSER_USER_AGENT},
            timeout_seconds=self._config.timeout_seconds,
        )
        if response.status_code >= 400:
            return ContractStatus.FAILED, None, response.body
        return ContractStatus.SUCCESS, response.body, None

    def _result(
        self,
        status: ContractStatus,
        data: Any = None,
        error: str | None = None,
        quality: DataQuality = DataQuality.FRESH,
    ) -> ProviderResult[Any]:
        return ProviderResult(
            status=status,
            provider=self.provider_id.value,
            metadata=ContractMetadata(),
            data=data,
            quality=quality if status == ContractStatus.SUCCESS else DataQuality.UNKNOWN,
            error=error,
        )

    def _provider_symbol(self, symbol: MarketSymbol) -> str:
        return self._config.symbol_map.get(symbol.value, symbol.value)


class TwelveDataMarketDataClient(BaseApiClient):
    def get_quote(self, symbol: MarketSymbol) -> ProviderResult[MarketQuote]:
        if "quote" not in self._config.endpoints:
            return self._result(
                ContractStatus.FAILED,
                error=(
                    "Twelve Data quote endpoint is not configured; "
                    "XAU/USD quote is derived from time_series data."
                ),
            )
        provider_symbol = self._provider_symbol(symbol)
        status, payload, error = self._get_json("quote", {"symbol": provider_symbol})
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            quote = MarketQuote(
                symbol=symbol,
                provider_symbol=provider_symbol,
                price=_decimal_from_any(payload.get("price") or payload.get("close")),
                bid=_optional_decimal(payload.get("bid")),
                ask=_optional_decimal(payload.get("ask")),
                timestamp=_parse_timestamp(
                    payload.get("timestamp") or payload.get("datetime") or payload.get("date")
                ),
                provider=DataProviderId.TWELVE_DATA,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
        return self._result(ContractStatus.SUCCESS, data=quote)

    def get_ohlc(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        output_size: int = 100,
    ) -> ProviderResult[tuple[OhlcBar, ...]]:
        provider_symbol = self._provider_symbol(symbol)
        status, payload, error = self._get_json(
            "time_series",
            {
                "symbol": provider_symbol,
                "interval": timeframe.value,
                "outputsize": str(output_size),
            },
        )
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)

        try:
            bars = tuple(
                OhlcBar(
                    symbol=symbol,
                    provider_symbol=provider_symbol,
                    timeframe=timeframe,
                    timestamp=_parse_timestamp(row["datetime"]),
                    open=_decimal_from_any(row["open"]),
                    high=_decimal_from_any(row["high"]),
                    low=_decimal_from_any(row["low"]),
                    close=_decimal_from_any(row["close"]),
                    volume=_optional_decimal(row.get("volume")),
                    provider=DataProviderId.TWELVE_DATA,
                )
                for row in payload.get("values", ())
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
        if not bars:
            return self._result(ContractStatus.NO_DATA, error="Twelve Data returned no OHLC rows.")
        return self._result(ContractStatus.SUCCESS, data=bars)


class FredMacroClient(BaseApiClient):
    def get_series_observations(
        self,
        series_id: str,
        observation_start: str | None = None,
        observation_end: str | None = None,
    ) -> ProviderResult[tuple[MacroSeriesObservation, ...]]:
        params = {"series_id": series_id, "file_type": "json"}
        if observation_start:
            params["observation_start"] = observation_start
        if observation_end:
            params["observation_end"] = observation_end

        status, payload, error = self._get_json("series_observations", params)
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            observations = tuple(
                MacroSeriesObservation(
                    series_id=series_id,
                    date=_parse_date(row["date"]),
                    value=_optional_decimal(row.get("value")),
                    provider=DataProviderId.FRED,
                )
                for row in payload.get("observations", ())
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
        return self._result(ContractStatus.SUCCESS, data=observations)


class NewsApiClient(BaseApiClient):
    def get_articles(self, query: str) -> ProviderResult[tuple[NewsArticle, ...]]:
        status, payload, error = self._get_json(
            "everything",
            {"q": query, "language": "en", "sortBy": "publishedAt"},
        )
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            articles = tuple(
                NewsArticle(
                    article_id=_stable_id(
                        DataProviderId.NEWSAPI.value,
                        str(row.get("url")),
                        str(row.get("publishedAt")),
                    ),
                    title=str(row.get("title")),
                    url=str(row.get("url")),
                    source_name=str(row.get("source", {}).get("name", "UNKNOWN")),
                    published_at=_parse_timestamp(row.get("publishedAt")),
                    summary=_optional_string(row.get("description")),
                    provider=DataProviderId.NEWSAPI,
                )
                for row in payload.get("articles", ())
                if row.get("title") and row.get("url") and row.get("publishedAt")
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
        return self._result(ContractStatus.SUCCESS, data=articles)


class GdeltNewsClient(BaseApiClient):
    def get_articles(self, query: str) -> ProviderResult[tuple[NewsArticle, ...]]:
        status, payload, error = self._get_json("doc_articles", {"query": query})
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            articles = tuple(
                NewsArticle(
                    article_id=_stable_id(
                        DataProviderId.GDELT.value,
                        str(row.get("url")),
                        str(row.get("seendate")),
                    ),
                    title=str(row.get("title")),
                    url=str(row.get("url")),
                    source_name=str(row.get("domain") or row.get("sourceCountry") or "UNKNOWN"),
                    published_at=_parse_timestamp(row.get("seendate")),
                    summary=None,
                    provider=DataProviderId.GDELT,
                )
                for row in payload.get("articles", ())
                if row.get("title") and row.get("url") and row.get("seendate")
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
        return self._result(ContractStatus.SUCCESS, data=articles)


class CftcCotClient(BaseApiClient):
    def get_gold_cot_positioning(self) -> ProviderResult[tuple[CotPositioningSnapshot, ...]]:
        status, payload, error = self._get_json("cot_disaggregated")
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            rows = [
                row
                for row in payload
                if "GOLD" in str(row.get("market_and_exchange_names", "")).upper()
            ]
            snapshots = tuple(
                CotPositioningSnapshot(
                    report_date=_parse_date(row["report_date_as_yyyy_mm_dd"]),
                    market_name=str(row["market_and_exchange_names"]),
                    managed_money_long=int(row["m_money_positions_long_all"]),
                    managed_money_short=int(row["m_money_positions_short_all"]),
                    managed_money_net=int(row["m_money_positions_long_all"])
                    - int(row["m_money_positions_short_all"]),
                )
                for row in rows
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
        return self._result(ContractStatus.SUCCESS, data=snapshots)


class SpdrGldClient(BaseApiClient):
    def get_latest_gld_flow(self) -> ProviderResult[EtfFlowSnapshot]:
        status, payload, error = self._get_json("gld_data")
        if status != ContractStatus.SUCCESS:
            return self._result(status, error=error)
        try:
            data = payload["data"]
            system = payload.get("system", {})
            fallback_date = _parse_timestamp(system.get("request_time"))
            total_ounces, total_ounces_date = _gld_field_value_and_date(
                data, "total_ounces", fallback_date
            )
            total_tonnes, total_tonnes_date = _gld_field_value_and_date(
                data, "total_tonnes", fallback_date
            )
            total_nav_usd, total_nav_date = _gld_field_value_and_date(
                data, "total_nav_usd", fallback_date
            )
            shares_outstanding, shares_date = _gld_field_value_and_date(
                data, "shares_outstanding", fallback_date
            )
            snapshot = EtfFlowSnapshot(
                date=total_ounces_date,
                fund="GLD",
                total_ounces=total_ounces,
                daily_ounce_change=None,
                total_tonnes=total_tonnes,
                total_nav_usd=total_nav_usd,
                shares_outstanding=shares_outstanding,
                field_dates={
                    "total_ounces": total_ounces_date,
                    "total_tonnes": total_tonnes_date,
                    "total_nav_usd": total_nav_date,
                    "shares_outstanding": shares_date,
                },
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            return self._result(ContractStatus.INVALID_INPUT, error=str(exc))
        return self._result(ContractStatus.SUCCESS, data=snapshot)


def _decimal_from_any(value: Any) -> Decimal:
    if value in (None, "", "."):
        raise ValueError("missing decimal value")
    return Decimal(str(value).replace(",", ""))


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, "", "."):
        return None
    return _decimal_from_any(value)


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _parse_money_or_number(raw: Any) -> Decimal:
    if raw in (None, ""):
        raise ValueError("missing numeric value")
    normalized = str(raw).replace("US$", "").replace(",", "").strip()
    if normalized in ("", "N/A", "."):
        raise ValueError(f"invalid numeric value: {raw}")
    return Decimal(normalized)


def _gld_field_value_and_date(
    data: dict[str, Any], field_name: str, fallback_date: datetime
) -> tuple[Decimal, datetime]:
    if field_name not in data:
        raise KeyError(f"Missing GLD field: {field_name}")
    field = data[field_name]
    value = _parse_money_or_number(field.get("value"))
    date = _parse_gld_field_date(field.get("date")) if field.get("date") else fallback_date
    return value, date


def _parse_gld_field_date(value: Any) -> datetime:
    parsed = datetime.strptime(str(value), "%B %d, %Y")
    return parsed.replace(tzinfo=UTC)


def _parse_date(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    raw = str(value)
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    if len(raw) == 8 and raw.isdigit():
        return datetime.strptime(raw, "%Y%m%d").replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return digest
