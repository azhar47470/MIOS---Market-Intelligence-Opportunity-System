from decimal import Decimal

from app.domain.enums import Recommendation
from app.paper_trading.engine import PaperTradingEngine
from app.paper_trading.repository import JsonPaperTradingRepository
from app.presentation.dashboard import _paper_trading_payload
from tests.test_orchestrator_backtesting_dashboard import (
    FakeMarketDataClient,
    GoldIntelligenceOrchestrator,
    IngestionClients,
    MemoryDecisionJournalRepository,
    low_threshold_config,
    make_bars,
)


def test_paper_trading_opens_closes_and_reports_physical_gold_pnl(tmp_path):
    repository = JsonPaperTradingRepository(tmp_path / "paper_trading.json")
    engine = PaperTradingEngine(repository)
    decision = _sample_decision()

    opened = engine.update(
        decision.model_copy(
            update={"recommendation": Recommendation.BUY, "recommendation_id": "buy-1"}
        ),
        Decimal("2300"),
    )
    closed = engine.update(
        decision.model_copy(
            update={
                "recommendation": Recommendation.TAKE_PROFIT,
                "recommendation_id": "take-profit-1",
            }
        ),
        Decimal("2325"),
    )
    summary = engine.summary()

    assert opened.open_position is not None
    assert closed.open_position is None
    assert closed.closed_positions[0].realized_pnl == Decimal("25")
    assert summary["closed_realized_pnl"] == "25"
    assert summary["hit_rate"] == "100"


def test_orchestrator_updates_paper_trading_when_real_quote_is_available(tmp_path):
    repository = JsonPaperTradingRepository(tmp_path / "paper_trading.json")
    journal = MemoryDecisionJournalRepository()
    orchestrator = GoldIntelligenceOrchestrator(
        ingestion_clients=IngestionClients(twelve_data=FakeMarketDataClient(make_bars())),
        decision_config=low_threshold_config(),
        decision_journal=journal,
        paper_trading_engine=PaperTradingEngine(repository),
    )

    result = orchestrator.run_once()

    assert result.paper_trading is not None
    assert result.paper_trading["last_price"] is not None


def test_dashboard_paper_trading_payload_reports_state(tmp_path):
    repository = JsonPaperTradingRepository(tmp_path / "paper_trading.json")
    engine = PaperTradingEngine(repository)
    decision = _sample_decision().model_copy(
        update={"recommendation": Recommendation.BUY, "recommendation_id": "buy-1"}
    )
    engine.update(decision, Decimal("2300"))

    payload = _paper_trading_payload(repository)

    assert payload["open_position"] is not None
    assert payload["open_unrealized_pnl"] == "0"
    assert payload["last_price"] == "2300"


def test_position_records_narratives_at_open(tmp_path):
    repository = JsonPaperTradingRepository(tmp_path / "paper_trading.json")
    engine = PaperTradingEngine(repository)
    decision = _sample_decision()

    opened = engine.update(
        decision.model_copy(
            update={"recommendation": Recommendation.BUY, "recommendation_id": "buy-1"}
        ),
        Decimal("2300"),
        narratives=("Rate Cut Cycle", "Central Bank Accumulation"),
    )

    assert opened.open_position.narratives == ("Rate Cut Cycle", "Central Bank Accumulation")


def test_summary_attributes_closed_pnl_by_narrative(tmp_path):
    repository = JsonPaperTradingRepository(tmp_path / "paper_trading.json")
    engine = PaperTradingEngine(repository)
    decision = _sample_decision()

    engine.update(
        decision.model_copy(
            update={"recommendation": Recommendation.BUY, "recommendation_id": "buy-1"}
        ),
        Decimal("2300"),
        narratives=("Rate Cut Cycle",),
    )
    engine.update(
        decision.model_copy(
            update={
                "recommendation": Recommendation.TAKE_PROFIT,
                "recommendation_id": "take-profit-1",
            }
        ),
        Decimal("2325"),
    )
    engine.update(
        decision.model_copy(
            update={"recommendation": Recommendation.BUY, "recommendation_id": "buy-2"}
        ),
        Decimal("2325"),
        narratives=("Rate Cut Cycle", "Dollar Weakness"),
    )
    engine.update(
        decision.model_copy(
            update={
                "recommendation": Recommendation.TAKE_PROFIT,
                "recommendation_id": "take-profit-2",
            }
        ),
        Decimal("2300"),
    )

    breakdown = engine.summary()["by_narrative"]

    assert breakdown["Rate Cut Cycle"]["trades"] == "2"
    assert breakdown["Rate Cut Cycle"]["win_rate"] == "50.0"
    assert breakdown["Rate Cut Cycle"]["total_pnl"] == "0"
    assert breakdown["Dollar Weakness"]["trades"] == "1"
    assert breakdown["Dollar Weakness"]["total_pnl"] == "-25"


def test_summary_without_closed_positions_has_empty_breakdown(tmp_path):
    repository = JsonPaperTradingRepository(tmp_path / "paper_trading.json")
    engine = PaperTradingEngine(repository)

    assert engine.summary()["by_narrative"] == {}


def _sample_decision():
    journal = MemoryDecisionJournalRepository()
    orchestrator = GoldIntelligenceOrchestrator(
        ingestion_clients=IngestionClients(twelve_data=FakeMarketDataClient(make_bars())),
        decision_config=low_threshold_config(),
        decision_journal=journal,
    )
    return orchestrator.run_once().decision
