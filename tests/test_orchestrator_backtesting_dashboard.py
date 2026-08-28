import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.application.backtesting import BacktestingEngine
from app.application.decision_config import DecisionEngineConfig, DecisionThresholdConfig
from app.application.event_bus import InMemoryEventBus
from app.application.orchestrator import GoldIntelligenceOrchestrator
from app.domain.common import ContractMetadata, ContractStatus, DataQuality, ProviderResult
from app.domain.enums import Recommendation
from app.domain.events import EventType
from app.domain.intelligence import EngineId
from app.domain.market_data import (
    DataProviderId,
    MarketQuote,
    MarketSymbol,
    OhlcBar,
    Timeframe,
)
from app.infrastructure.repositories.memory_decision_journal_repository import (
    MemoryDecisionJournalRepository,
)
from app.ingestion.factory import IngestionClients
from app.presentation.dashboard import (
    _engine_payload,
    _health_payload,
    warn_if_insecure_flask_secret,
    write_static_dashboard,
)


class FakeMarketDataClient:
    def __init__(self, bars: tuple[OhlcBar, ...]) -> None:
        self._bars = bars

    def get_quote(self, symbol: MarketSymbol) -> ProviderResult[MarketQuote]:
        return ProviderResult(
            status=ContractStatus.SUCCESS,
            provider=DataProviderId.TWELVE_DATA.value,
            metadata=ContractMetadata(),
            data=MarketQuote(
                symbol=symbol,
                provider_symbol=symbol.value,
                price=self._bars[-1].close,
                timestamp=self._bars[-1].timestamp,
                provider=DataProviderId.TWELVE_DATA,
            ),
            quality=DataQuality.FRESH,
        )

    def get_ohlc(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        output_size: int = 100,
    ) -> ProviderResult[tuple[OhlcBar, ...]]:
        return ProviderResult(
            status=ContractStatus.SUCCESS,
            provider=DataProviderId.TWELVE_DATA.value,
            metadata=ContractMetadata(),
            data=self._bars[-output_size:],
            quality=DataQuality.FRESH,
        )


def make_bars(count: int = 45) -> tuple[OhlcBar, ...]:
    start = datetime(2026, 7, 2, 0, 0, tzinfo=UTC)
    bars = []
    for index in range(count):
        close = Decimal("2300") + Decimal(index)
        bars.append(
            OhlcBar(
                symbol=MarketSymbol.XAU_USD,
                provider_symbol="XAU/USD",
                timeframe=Timeframe.ONE_HOUR,
                timestamp=start + timedelta(hours=index),
                open=close - Decimal("1"),
                high=close + Decimal("4"),
                low=close - Decimal("4"),
                close=close,
                provider=DataProviderId.TWELVE_DATA,
            )
        )
    return tuple(bars)


def low_threshold_config() -> DecisionEngineConfig:
    return DecisionEngineConfig(
        thresholds=DecisionThresholdConfig(
            minimum_confidence_for_action=1,
            physical_minimum_opportunity_score=1,
            forex_minimum_opportunity_score=1,
            etf_minimum_opportunity_score=1,
            minimum_expected_move_usd=Decimal("1"),
            max_high_severity_risks_for_action=10,
        )
    )


def test_orchestrator_runs_cycle_and_persists_decision():
    journal = MemoryDecisionJournalRepository()
    event_bus = InMemoryEventBus()
    orchestrator = GoldIntelligenceOrchestrator(
        ingestion_clients=IngestionClients(twelve_data=FakeMarketDataClient(make_bars())),
        decision_config=low_threshold_config(),
        decision_journal=journal,
        event_bus=event_bus,
    )

    result = orchestrator.run_once()

    assert result.decision.recommendation in set(Recommendation)
    assert journal.latest() == result.decision
    assert result.provider_statuses["twelve_data_ohlc"] == ContractStatus.SUCCESS
    assert {item.engine for item in result.decision.engine_breakdown} >= {
        EngineId.TECHNICAL,
        EngineId.FUNDAMENTAL,
        EngineId.INSTITUTIONAL,
        EngineId.NEWS,
        EngineId.GEOPOLITICAL,
        EngineId.MARKET_REGIME,
    }
    assert all(item.runtime_ms >= 0 for item in result.decision.engine_breakdown)
    assert EventType.MARKET_UPDATED in {event.event_type for event in event_bus.published_events}
    assert EventType.RECOMMENDATION_CHANGED in {
        event.event_type for event in event_bus.published_events
    }


def test_backtesting_engine_reuses_decision_flow():
    result = BacktestingEngine(low_threshold_config()).run(make_bars(), lookback=20, horizon=3)

    assert result.samples
    assert result.action_count + result.wait_count == len(result.samples)


def test_dashboard_export_writes_usable_html(tmp_path):
    output = tmp_path / "dashboard.html"

    write_static_dashboard(output)

    html = output.read_text(encoding="utf-8")
    assert "MIOS" in html
    assert "/api/latest" in html
    assert "REASON" in html


def test_dashboard_warns_when_flask_secret_is_default(monkeypatch, caplog):
    monkeypatch.setenv("FLASK_SECRET", "change_me")

    with caplog.at_level(logging.WARNING, logger="mios.dashboard"):
        warn_if_insecure_flask_secret()

    assert "FLASK_SECRET is unset or still set to 'change_me'" in caplog.text


def test_dashboard_secret_warning_is_quiet_for_custom_secret(monkeypatch, caplog):
    monkeypatch.setenv("FLASK_SECRET", "custom-secret")

    with caplog.at_level(logging.WARNING, logger="mios.dashboard"):
        warn_if_insecure_flask_secret()

    assert "FLASK_SECRET" not in caplog.text


def test_dashboard_engine_payload_uses_journal_breakdown():
    journal = MemoryDecisionJournalRepository()
    orchestrator = GoldIntelligenceOrchestrator(
        ingestion_clients=IngestionClients(twelve_data=FakeMarketDataClient(make_bars())),
        decision_config=low_threshold_config(),
        decision_journal=journal,
    )

    decision = orchestrator.run_once().decision
    payload = _engine_payload(decision, EngineId.TECHNICAL)

    assert payload["engine"] == EngineId.TECHNICAL.value
    assert payload["latest"] is not None
    assert payload["latest"]["score"] >= 0
    assert payload["latest"]["evidence"]


def test_dashboard_health_exposes_persisted_runtime_telemetry():
    journal = MemoryDecisionJournalRepository()
    orchestrator = GoldIntelligenceOrchestrator(
        ingestion_clients=IngestionClients(twelve_data=FakeMarketDataClient(make_bars())),
        decision_config=low_threshold_config(),
        decision_journal=journal,
    )

    decision = orchestrator.run_once().decision
    health = _health_payload(decision)

    assert all("runtime_ms" in engine for engine in health["engines"])
    assert health["ai"] == {
        "requests": 0,
        "runtime_ms": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }
