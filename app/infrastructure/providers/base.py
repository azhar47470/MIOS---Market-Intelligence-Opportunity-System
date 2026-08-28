import csv
import json
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from typing import Any

from app.application.http import HttpClient
from app.application.platform_config import ApiProviderConfig, AuthMode
from app.domain.common import ContractMetadata, ContractStatus, DataQuality, ProviderResult
from app.domain.market_data import MarketSymbol

logger = logging.getLogger("mios.providers")

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ProviderBase:
    def __init__(self, config: ApiProviderConfig, http_client: HttpClient) -> None:
        self._config = config
        self._http_client = http_client

    def _url(self, endpoint_name: str) -> str:
        endpoint = self._config.endpoints[endpoint_name]
        path = endpoint.path
        if path.startswith("http"):
            return path
        return f"{self._config.base_url}{path}"

    def _endpoint_params(self, endpoint_name: str) -> dict[str, str]:
        return dict(self._config.endpoints[endpoint_name].query_params)

    def _symbol(self, symbol: MarketSymbol) -> str:
        return self._config.symbol_map.get(symbol.value, symbol.value)

    def _auth_params(self) -> dict[str, str]:
        if self._config.auth_mode != AuthMode.QUERY_PARAM:
            return {}
        if self._config.api_key_env is None or self._config.api_key_param is None:
            return {}
        api_key = os.getenv(self._config.api_key_env)
        if not api_key:
            return {}
        return {self._config.api_key_param: api_key}

    def _missing_secret_error(self) -> str | None:
        if self._config.auth_mode == AuthMode.NONE or self._config.api_key_env is None:
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
            logger.warning(
                "%s failed on endpoint %s: %s",
                self.__class__.__name__,
                endpoint_name,
                secret_error,
            )
            return ContractStatus.FAILED, None, secret_error
        response = self._http_client.get(
            self._url(endpoint_name),
            params={
                **self._endpoint_params(endpoint_name),
                **(params or {}),
                **self._auth_params(),
            },
            headers=_browser_headers(),
            timeout_seconds=self._config.timeout_seconds,
        )
        if response.status_code >= 400:
            logger.warning(
                "%s failed on endpoint %s: %s",
                self.__class__.__name__,
                endpoint_name,
                response.body,
            )
            return ContractStatus.FAILED, None, response.body
        if not response.body or not response.body.strip():
            error_message = (
                f"{self._config.provider_id.value} returned an empty response body "
                "(likely rate-limited or temporarily unavailable)."
            )
            logger.warning(
                "%s failed on endpoint %s: %s",
                self.__class__.__name__,
                endpoint_name,
                error_message,
            )
            return ContractStatus.NO_DATA, None, error_message
        try:
            return ContractStatus.SUCCESS, json.loads(response.body), None
        except json.JSONDecodeError as error:
            error_message = str(error)
            logger.warning(
                "%s failed on endpoint %s: %s",
                self.__class__.__name__,
                endpoint_name,
                error_message,
            )
            return ContractStatus.INVALID_INPUT, None, error_message

    def _get_csv(
        self,
        endpoint_name: str,
        params: dict[str, str] | None = None,
    ) -> tuple[ContractStatus, list[dict[str, str]] | None, str | None]:
        status, text, error = self._get_text(endpoint_name, params)
        if status != ContractStatus.SUCCESS:
            return status, None, error
        try:
            rows = list(csv.DictReader(StringIO(text or "")))
        except csv.Error as error:
            error_message = str(error)
            logger.warning(
                "%s failed on endpoint %s: %s",
                self.__class__.__name__,
                endpoint_name,
                error_message,
            )
            return ContractStatus.INVALID_INPUT, None, error_message
        return ContractStatus.SUCCESS, rows, None

    def _get_text(
        self,
        endpoint_name: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[ContractStatus, str | None, str | None]:
        secret_error = self._missing_secret_error()
        if secret_error:
            logger.warning(
                "%s failed on endpoint %s: %s",
                self.__class__.__name__,
                endpoint_name,
                secret_error,
            )
            return ContractStatus.FAILED, None, secret_error
        response = self._http_client.get(
            self._url(endpoint_name),
            params={
                **self._endpoint_params(endpoint_name),
                **(params or {}),
                **self._auth_params(),
            },
            headers=headers or _browser_headers(),
            timeout_seconds=self._config.timeout_seconds,
        )
        if response.status_code >= 400:
            logger.warning(
                "%s failed on endpoint %s: %s",
                self.__class__.__name__,
                endpoint_name,
                response.body,
            )
            return ContractStatus.FAILED, None, response.body
        return ContractStatus.SUCCESS, response.body, None

    def _result(
        self,
        status: ContractStatus,
        data: Any = None,
        error: str | None = None,
    ) -> ProviderResult[Any]:
        return ProviderResult(
            status=status,
            provider=self._config.provider_id.value,
            metadata=ContractMetadata(),
            data=data,
            quality=DataQuality.FRESH if status == ContractStatus.SUCCESS else DataQuality.UNKNOWN,
            error=error,
        )


def decimal_from_any(value: Any) -> Decimal:
    if value in (None, "", "."):
        raise ValueError("missing decimal value")
    return Decimal(str(value).replace(",", ""))


def _browser_headers() -> dict[str, str]:
    return {"User-Agent": BROWSER_USER_AGENT}


def optional_decimal(value: Any) -> Decimal | None:
    if value in (None, "", "."):
        return None
    return decimal_from_any(value)


def parse_datetime(value: Any) -> datetime:
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
