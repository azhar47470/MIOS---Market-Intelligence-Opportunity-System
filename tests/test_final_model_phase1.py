from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.ai.rag import KnowledgeRetriever
from app.application.backtesting import BacktestingEngine
from app.application.gold_price_service import (
    GoldPriceService,
    MIN_SANITY_PRICE,
    MAX_SANITY_PRICE,
)
from app.application.http import HttpResponse
from app.application.knowledge_base import KnowledgeRepository
from app.domain.ai import AIContext
from app.domain.common import ContractStatus
from app.domain.knowledge import KnowledgeCategory, KnowledgeRecord
from app.domain.market_data import OhlcBar, Timeframe
from app.features.technical_features import build_technical_features


class MemoryKnowledgeRepository(KnowledgeRepository):
    def __init__(self, records: tuple[KnowledgeRecord, ...] = ()) -> None:
        self._records = records

    def upsert(self, record: KnowledgeRecord) -> None:
        self._records = (*self._records, record)

    def get(self, record_id: str) -> KnowledgeRecord | None:
        return next((r for r in self._records if r.record_id == record_id), None)

    def search(
        self,
        query: str,
        category: KnowledgeCategory | None = None,
        limit: int = 20,
    ) -> tuple[KnowledgeRecord, ...]:
        query_lower = query.lower()
        matches = [
            record
            for record in self._records
            if query_lower in f"{record.title} {record.body} {' '.join(record.tags)}".lower()
        ]
        return tuple(matches[:limit])


def test_knowledge_retriever_injects_records_into_context_facts():
    record = KnowledgeRecord(
        record_id="macro-001",
        category=KnowledgeCategory.MACRO_HISTORY,
        title="Real yields drive gold",
        body="Falling real yields historically support gold over 1-4 week horizons.",
        tags=("real yields", "gold"),
    )
    retriever = KnowledgeRetriever(MemoryKnowledgeRepository((record,)))
    context = AIContext(
        context_id="c1", objective="test", facts={"technical_score": 70}
    )

    enriched = retriever.enrich(context, query="gold real yields")

    assert enriched.retrieved_record_ids == ("macro-001",)
    assert enriched.facts["knowledge_records"][0]["title"] == "Real yields drive gold"
    assert enriched.facts["technical_score"] == 70
    assert context.facts.get("knowledge_records") is None


def test_knowledge_retriever_leaves_context_untouched_without_matches():
    retriever = KnowledgeRetriever(MemoryKnowledgeRepository())
    context = AIContext(context_id="c1", objective="test", facts={"a": 1})

    enriched = retriever.enrich(context, query="nothing matches")

    assert enriched.retrieved_record_ids == ()
    assert enriched.facts == {"a": 1}
    assert "knowledge_records" not in enriched.facts


def _bar(index: int, timeframe: Timeframe, close: Decimal) -> OhlcBar:
    return OhlcBar(
        symbol="XAU/USD",
        provider_symbol="XAU/USD",
        timeframe=timeframe,
        timestamp=datetime(2026, 8, 1, tzinfo=UTC) + timedelta(hours=index),
        open=close - Decimal("1"),
        high=close + Decimal("2"),
        low=close - Decimal("3"),
        close=close,
        volume=Decimal("1000"),
        provider="twelve_data",
    )


def test_technical_features_handles_mixed_timeframe_window_with_few_primary_bars():
    bars = tuple(_bar(i, Timeframe.FOUR_HOURS, Decimal("4000") + i) for i in range(60))
    bars += tuple(_bar(i + 100, Timeframe.ONE_HOUR, Decimal("4050") + i) for i in range(3))

    features = build_technical_features(bars)

    assert features.candle_count == 3
    assert features.latest_close is None


def test_backtesting_engine_runs_on_synthetic_history():
    bars = tuple(_bar(i, Timeframe.ONE_HOUR, Decimal("4000") + i) for i in range(90))

    from app.infrastructure.config_loader import load_decision_engine_config
    from pathlib import Path

    engine = BacktestingEngine(
        load_decision_engine_config(Path("config/decision_engine.json"))
    )
    result = engine.run(bars=bars, lookback=60, horizon=5)

    assert len(result.samples) == 26
    assert result.action_count + result.wait_count == 26
    assert 0 <= result.directional_hit_rate <= 1


class ScriptedPriceClient:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        self.urls.append(url)
        if not self._responses:
            return HttpResponse(status_code=599, body="no more responses")
        return self._responses.pop(0)

    def post(self, url, body, params=None, headers=None, timeout_seconds=10.0):
        raise AssertionError("price service should not POST")


def _price_response(price: str) -> HttpResponse:
    return HttpResponse(status_code=200, body=f'{{"price": "{price}"}}')


def test_gold_price_service_takes_first_valid_source():
    client = ScriptedPriceClient([_price_response("4050.25")])

    result = GoldPriceService(client).fetch_quote()

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data.price == Decimal("4050.25")
    assert result.data.provider.value == "gold_api"
    assert client.urls[0].startswith("https://api.gold-api.com")


def test_gold_price_service_falls_back_when_first_source_is_garbage():
    client = ScriptedPriceClient(
        [
            HttpResponse(status_code=500, body="boom"),  # gold-api down
            HttpResponse(status_code=200, body="[{\"gold\": \"4048.90\"}]"),  # metals.live
        ]
    )

    result = GoldPriceService(client).fetch_quote()

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data.price == Decimal("4048.90")
    assert result.data.provider.value == "metals_live"


def test_gold_price_service_rejects_out_of_range_price_and_keeps_going():
    client = ScriptedPriceClient(
        [
            _price_response("999999"),  # garbage
            HttpResponse(status_code=200, body="[]"),  # metals.live: no usable item
            HttpResponse(
                status_code=200,
                body='{"chart":{"result":[{"meta":{"regularMarketPrice": 4052.1}}]}}',
            ),
        ]
    )

    result = GoldPriceService(client).fetch_quote()

    assert result.status == ContractStatus.SUCCESS
    assert result.data is not None
    assert result.data.price == Decimal("4052.10")
    assert result.data.provider.value == "yahoo"


def test_gold_price_service_reports_failure_when_all_sources_fail():
    client = ScriptedPriceClient(
        [
            HttpResponse(status_code=599, body="timeout"),
            HttpResponse(status_code=599, body="timeout"),
            HttpResponse(status_code=599, body="timeout"),
        ]
    )

    result = GoldPriceService(client).fetch_quote()

    assert result.status == ContractStatus.FAILED
    assert "HTTP 599" in (result.error or "")


def test_gold_price_service_caps_long_aggregated_failure_error():
    class ExplodingPriceClient(ScriptedPriceClient):
        def get(self, url, params=None, headers=None, timeout_seconds=10.0):
            self.urls.append(url)
            raise RuntimeError("upstream failure detail " + "x" * 900)

    client = ExplodingPriceClient([])

    result = GoldPriceService(client).fetch_quote()

    assert result.status == ContractStatus.FAILED
    assert result.data is None
    assert result.error is not None
    assert len(result.error) <= 1000
    # The beginning of the diagnostic chain survives truncation.
    assert result.error.startswith("gold-api.com: upstream failure detail")
