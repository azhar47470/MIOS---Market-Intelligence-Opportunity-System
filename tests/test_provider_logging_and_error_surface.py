import asyncio
import logging

from app.application.engines.fundamental_engine import FundamentalIntelligenceEngine
from app.application.engines.institutional_engine import InstitutionalIntelligenceEngine
from app.application.http import HttpResponse
from app.domain.common import ContractStatus
from app.domain.market_data import DataProviderId, Timeframe
from app.infrastructure.config_loader import load_platform_config
from app.infrastructure.providers.cot_provider import COTProvider
from app.infrastructure.providers.twelve_data_provider import TwelveDataProvider


class FakeHttpClient:
    def __init__(self, response: HttpResponse) -> None:
        self._response = response

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        return self._response

    def post(self, url, body, params=None, headers=None, timeout_seconds=10.0):
        raise AssertionError("provider test should not POST")


def test_base_provider_logs_missing_secret_warning(monkeypatch, caplog):
    config = load_platform_config("config/platform.json")
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    provider = TwelveDataProvider(
        config.providers[DataProviderId.TWELVE_DATA],
        FakeHttpClient(HttpResponse(status_code=200, body="{}")),
    )

    with caplog.at_level(logging.WARNING, logger="mios.providers"):
        result = asyncio.run(provider.gold_ohlc(Timeframe.ONE_HOUR))

    assert result.status == ContractStatus.FAILED
    assert result.error == "Required environment variable TWELVE_DATA_API_KEY is not set."
    assert "TwelveDataProvider failed on endpoint time_series" in caplog.text
    assert "TWELVE_DATA_API_KEY" in caplog.text


def test_provider_logs_parsing_error_warning(caplog):
    config = load_platform_config("config/platform.json")
    provider = COTProvider(
        config.providers[DataProviderId.CFTC_COT],
        FakeHttpClient(
            HttpResponse(
                status_code=200,
                body='[{"market_and_exchange_names":"GOLD - COMMODITY EXCHANGE INC."}]',
            )
        ),
    )

    with caplog.at_level(logging.WARNING, logger="mios.providers"):
        result = asyncio.run(provider.latest_gold_positions())

    assert result.status == ContractStatus.INVALID_INPUT
    assert "COTProvider parsing failed" in caplog.text


def test_institutional_engine_evidence_includes_provider_error_text():
    result = InstitutionalIntelligenceEngine().analyze(
        (),
        None,
        {"cot": "CFTC HTTP 503", "gld": "GLD data timeout"},
    )

    descriptions = {evidence.category: evidence.description for evidence in result.evidence}
    assert descriptions["COT Positioning"] == "COT data unavailable: CFTC HTTP 503"
    assert descriptions["ETF Flows"] == "GLD flow delta unavailable: GLD data timeout"


def test_fundamental_engine_evidence_includes_dxy_error_text():
    result = FundamentalIntelligenceEngine().analyze((), (), {"dxy": "FRED API key rejected"})

    assert (
        result.evidence[0].description
        == "DXY data is unavailable or insufficient: FRED API key rejected"
    )
