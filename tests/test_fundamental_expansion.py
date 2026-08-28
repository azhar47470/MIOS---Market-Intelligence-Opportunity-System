import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.application.engines.fundamental_engine import FundamentalIntelligenceEngine
from app.application.http import HttpResponse
from app.domain.common import ContractStatus
from app.domain.market_data import DataProviderId, MacroSeriesObservation
from app.infrastructure.config_loader import load_platform_config
from app.infrastructure.providers.fred_macro_provider import FREDMacroProvider


class FakeHttpClient:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requests: list[dict] = []

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        self.requests.append(
            {"url": url, "params": params or {}, "headers": headers or {}}
        )
        return self.response

    def post(self, url, body, params=None, headers=None, timeout_seconds=10.0):
        raise AssertionError("FRED macro provider should not issue POST requests")


def test_fred_macro_provider_returns_typed_observations(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-fred-key")
    payload = {
        "observations": [
            {"date": "2026-06-01", "value": "4.10"},
            {"date": "2026-07-01", "value": "4.00"},
            {"date": "2026-07-02", "value": "."},
        ]
    }
    http = FakeHttpClient(HttpResponse(status_code=200, body=json.dumps(payload)))
    config = load_platform_config("config/platform.json")
    provider = FREDMacroProvider(config.providers[DataProviderId.FRED], http)

    result = asyncio.run(provider.series_observations("DFII10"))

    assert result.status is ContractStatus.SUCCESS
    assert result.data is not None
    assert [item.value for item in result.data] == [Decimal("4.10"), Decimal("4.00")]
    assert http.requests[0]["params"]["series_id"] == "DFII10"
    assert http.requests[0]["params"]["api_key"] == "test-fred-key"


def test_fundamental_engine_emits_structured_macro_evidence():
    now = datetime(2026, 7, 14, tzinfo=UTC)
    dxy = (
        _observation("DXY", now - timedelta(days=1), "105"),
        _observation("DXY", now, "104"),
    )
    macro = (
        _observation("FEDFUNDS", now - timedelta(days=30), "5.00"),
        _observation("FEDFUNDS", now, "4.75"),
        _observation("DFII10", now - timedelta(days=30), "2.10"),
        _observation("DFII10", now, "2.00"),
        _observation("CPIAUCSL", now - timedelta(days=30), "320"),
        _observation("CPIAUCSL", now, "321"),
        _observation("PAYEMS", now - timedelta(days=30), "160000"),
        _observation("PAYEMS", now, "159000"),
        _observation("GDPC1", now - timedelta(days=90), "23000"),
        _observation("GDPC1", now, "23100"),
        _observation("T10Y2Y", now - timedelta(days=1), "0.50"),
        _observation("T10Y2Y", now, "0.45"),
    )

    result = FundamentalIntelligenceEngine().analyze(dxy, (), macro_observations=macro)

    categories = {evidence.category for evidence in result.evidence}
    assert {
        "Fed Policy",
        "Real Yields",
        "Inflation Trend",
        "Employment Trend",
        "GDP Trend",
        "Yield Curve",
        "Central Bank Gold Purchases",
    } <= categories
    assert result.confidence.value > 75
    assert result.macro_narrative.endswith(
        "macro series. No immediate high-impact US macro event is blocking normal analysis."
    )


def _observation(series_id: str, date: datetime, value: str) -> MacroSeriesObservation:
    return MacroSeriesObservation(
        series_id=series_id,
        date=date,
        value=Decimal(value),
        provider=DataProviderId.FRED,
    )
