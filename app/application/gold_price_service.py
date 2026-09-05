"""Multi-source spot gold price with a fallback chain and sanity range check.

Chain order: gold-api.com -> metals.live -> Yahoo Finance quote API. Every candidate
price is sanity-checked against a wide physical range (800-15000 USD/oz) so a garbled
API response can never poison the quote; sources that fail or return out-of-range
values are skipped and the next one is tried. The caller's repository quote remains
the primary source — this service is the resilience net when it is missing, plus a
cheap cross-check used by paper trading and the dashboard.
"""

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.application.http import HttpClient
from app.domain.common import ContractStatus, ProviderResult
from app.domain.market_data import DataProviderId, MarketQuote, MarketSymbol

logger = logging.getLogger("mios.gold_price")

MIN_SANITY_PRICE = Decimal("800")
MAX_SANITY_PRICE = Decimal("15000")

_SOURCE_PROVIDERS = {
    "gold-api.com": DataProviderId.GOLD_API,
    "metals.live": DataProviderId.METALS_LIVE,
    "yahoo": DataProviderId.YAHOO,
}


class GoldPriceService:
    def __init__(self, http_client: HttpClient) -> None:
        self._http_client = http_client

    def fetch_quote(
        self,
        provider_symbol: str = "XAU/USD",
        timeout_seconds: float = 10.0,
    ) -> ProviderResult[MarketQuote]:
        attempts = (
            ("gold-api.com", self._fetch_gold_api),
            ("metals.live", self._fetch_metals_live),
            ("yahoo", self._fetch_yahoo),
        )
        failures: list[str] = []
        for source, fetch in attempts:
            try:
                raw_price = fetch(timeout_seconds)
            except Exception as error:  # noqa: BLE001 - every source must degrade
                logger.warning("Gold price source %s failed: %s", source, error)
                failures.append(f"{source}: {error}")
                continue
            if raw_price is None:
                failures.append(f"{source}: no price in payload")
                continue
            if not (MIN_SANITY_PRICE < raw_price < MAX_SANITY_PRICE):
                logger.warning(
                    "Gold price from %s out of sanity range: %s", source, raw_price
                )
                failures.append(f"{source}: out of range")
                continue
            logger.info("Gold spot: %s USD via %s", raw_price, source)
            return ProviderResult(
                status=ContractStatus.SUCCESS,
                provider=source,
                data=MarketQuote(
                    symbol=MarketSymbol.XAU_USD,
                    provider_symbol=provider_symbol,
                    price=raw_price.quantize(Decimal("0.01")),
                    timestamp=datetime.now(UTC),
                    provider=_SOURCE_PROVIDERS[source],
                ),
            )
        return ProviderResult(
            status=ContractStatus.FAILED,
            provider="gold_price_service",
            # ProviderResult.error is capped at 1000 chars; long aggregated
            # failure chains must truncate instead of raising ValidationError.
            error=("; ".join(failures) or "No gold price source configured")[:1000],
        )

    def _fetch_gold_api(self, timeout_seconds: float) -> Decimal | None:
        response = self._http_client.get(
            "https://api.gold-api.com/price/XAU", timeout_seconds=timeout_seconds
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}")
        payload = json.loads(response.body)
        return _to_decimal(payload.get("price"))

    def _fetch_metals_live(self, timeout_seconds: float) -> Decimal | None:
        response = self._http_client.get(
            "https://api.metals.live/v1/spot/gold", timeout_seconds=timeout_seconds
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}")
        payload = json.loads(response.body)
        item = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(item, dict):
            return None
        for key in ("gold", "price", "spot"):
            if item.get(key):
                return _to_decimal(item[key])
        return None

    def _fetch_yahoo(self, timeout_seconds: float) -> Decimal | None:
        response = self._http_client.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout_seconds=timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}")
        payload = json.loads(response.body)
        meta = payload["chart"]["result"][0]["meta"]
        return _to_decimal(meta.get("regularMarketPrice"))


def _to_decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
