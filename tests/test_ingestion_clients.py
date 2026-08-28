from decimal import Decimal

import pytest

from app.application.http import HttpResponse
from app.domain.common import ContractStatus
from app.domain.market_data import DataProviderId, MarketSymbol, Timeframe
from app.infrastructure.config_loader import load_platform_config
from app.infrastructure.ingestion.api_clients import (
    CftcCotClient,
    FredMacroClient,
    SpdrGldClient,
    TwelveDataMarketDataClient,
)


class FakeHttpClient:
    def __init__(self, body: str, status_code: int = 200) -> None:
        self.body = body
        self.status_code = status_code
        self.requests = []

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        self.requests.append(
            {
                "url": url,
                "params": params or {},
                "headers": headers or {},
                "timeout_seconds": timeout_seconds,
            }
        )
        return HttpResponse(status_code=self.status_code, body=self.body)


@pytest.fixture
def platform_config():
    return load_platform_config("config/platform.json")


def test_twelve_data_quote_endpoint_removed_fails_explicitly(platform_config, monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    http = FakeHttpClient("{}")
    client = TwelveDataMarketDataClient(platform_config.providers[DataProviderId.TWELVE_DATA], http)

    result = client.get_quote(MarketSymbol.XAU_USD)

    assert result.status == ContractStatus.FAILED
    assert "quote endpoint is not configured" in str(result.error)
    assert http.requests == []


def test_twelve_data_returns_failed_result_when_secret_missing(platform_config, monkeypatch):
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    http = FakeHttpClient("{}")
    client = TwelveDataMarketDataClient(platform_config.providers[DataProviderId.TWELVE_DATA], http)

    result = client.get_ohlc(MarketSymbol.XAU_USD, Timeframe.ONE_HOUR)

    assert result.status == ContractStatus.FAILED
    assert result.error is not None
    assert http.requests == []


def test_twelve_data_ohlc_maps_structured_bars(platform_config, monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")
    http = FakeHttpClient("""
        {
          "values": [
            {
              "datetime": "2026-07-02T12:00:00+00:00",
              "open": "2340.00",
              "high": "2355.00",
              "low": "2338.00",
              "close": "2350.00",
              "volume": "1200"
            }
          ]
        }
        """)
    client = TwelveDataMarketDataClient(platform_config.providers[DataProviderId.TWELVE_DATA], http)

    result = client.get_ohlc(MarketSymbol.XAU_USD, Timeframe.ONE_HOUR)

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data[0].timeframe == Timeframe.ONE_HOUR
    assert result.data[0].close == Decimal("2350.00")


def test_fred_observations_parse_daily_macro_series(platform_config, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    http = FakeHttpClient("""
        {
          "observations": [
            {"date": "2026-07-01", "value": "101.25"},
            {"date": "2026-07-02", "value": "."}
          ]
        }
        """)
    client = FredMacroClient(platform_config.providers[DataProviderId.FRED], http)

    result = client.get_series_observations("DTWEXBGS")

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data[0].value == Decimal("101.25")
    assert result.data[1].value is None


def test_cftc_gold_positioning_filters_gold_rows(platform_config):
    http = FakeHttpClient("""
        [
          {
            "report_date_as_yyyy_mm_dd": "2026-06-30",
            "market_and_exchange_names": "GOLD - COMMODITY EXCHANGE INC.",
            "m_money_positions_long_all": "180000",
            "m_money_positions_short_all": "90000"
          },
          {
            "report_date_as_yyyy_mm_dd": "2026-06-30",
            "market_and_exchange_names": "SILVER - COMMODITY EXCHANGE INC.",
            "m_money_positions_long_all": "100",
            "m_money_positions_short_all": "90"
          }
        ]
        """)
    client = CftcCotClient(platform_config.providers[DataProviderId.CFTC_COT], http)

    result = client.get_gold_cot_positioning()

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert len(result.data) == 1
    assert result.data[0].managed_money_net == 90000


GLD_SAMPLE_JSON = """
{
  "data": {
    "shares_outstanding": {"value": "351,200,000", "date": "July 6, 2026"},
    "total_nav_usd": {"value": "US$ 133,453,392,018.02", "date": "July 6, 2026"},
    "total_ounces": {"value": "32,240,810.93", "date": "July 6, 2026"},
    "total_tonnes": {"value": "1,002.793", "date": "July 6, 2026"}
  },
  "system": {"request_time": "2026-07-06 22:14:00"}
}
"""


def test_spdr_gld_latest_flow_uses_live_data_endpoint(platform_config):
    http = FakeHttpClient(GLD_SAMPLE_JSON)
    client = SpdrGldClient(platform_config.providers[DataProviderId.SPDR_GLD], http)

    result = client.get_latest_gld_flow()

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data.total_ounces == Decimal("32240810.93")
    assert result.data.total_tonnes == Decimal("1002.793")
    assert result.data.total_nav_usd == Decimal("133453392018.02")
    assert result.data.shares_outstanding == Decimal("351200000")
    assert result.data.daily_ounce_change is None
    assert http.requests[0]["params"] == {"product": "gld", "exchange": "NYSE", "lang": "en"}
