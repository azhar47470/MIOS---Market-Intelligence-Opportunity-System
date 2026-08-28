import argparse
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
from pathlib import Path

from app.ai.agents.llm_client import LLMJsonClient
from app.ai.agents.news_analyst import GroqNewsAnalystAgent
from app.ai.rag import KnowledgeRetriever
from app.ai.research_desk import AIResearchDesk
from app.ai.validator import AIJsonValidator
from app.application.backtesting import BacktestingEngine
from app.application.decision_journal import DecisionJournalRepository
from app.application.engines.geopolitical_engine import GeopoliticalIntelligenceEngine
from app.application.engines.news_engine import NewsIntelligenceEngine
from app.application.events.pipeline import EventNarrativePipeline
from app.application.gold_price_service import GoldPriceService
from app.application.notification_engine import NotificationEngine
from app.application.orchestrator import GoldIntelligenceOrchestrator
from app.application.platform_config import PlatformConfig
from app.domain.market_data import DataProviderId, Timeframe
from app.infrastructure.config_loader import (
    load_ai_research_config,
    load_decision_engine_config,
    load_notification_config,
    load_platform_config,
)
from app.infrastructure.discord.webhook_client import DiscordWebhookPublisher
from app.infrastructure.http.urllib_http_client import UrlLibHttpClient
from app.infrastructure.providers.factory import build_provider_runtime
from app.infrastructure.providers.twelve_data_provider import TwelveDataProvider
from app.infrastructure.repositories.json_decision_journal_repository import (
    JsonDecisionJournalRepository,
)
from app.infrastructure.repositories.json_knowledge_repository import JsonKnowledgeRepository
from app.infrastructure.repositories.json_notification_state_repository import (
    JsonNotificationStateRepository,
)
from app.infrastructure.repositories.sqlite_decision_journal_repository import (
    SqliteDecisionJournalRepository,
)
from app.ingestion.factory import IngestionClients
from app.paper_trading.engine import PaperTradingEngine
from app.paper_trading.repository import JsonPaperTradingRepository
from app.presentation.dashboard import (
    serve_dashboard,
    warn_if_insecure_flask_secret,
    write_static_dashboard,
)
from app.scheduler.continuous_runner import ContinuousRunner

DEFAULT_CONFIG_DIR = Path("config")
DEFAULT_DATA_DIR = Path("data")
DEFAULT_KNOWLEDGE_DIR = Path("knowledge")
LOG_FILE = Path("logs") / "mios.log"


def main() -> None:
    _make_console_encoding_safe()
    parser = argparse.ArgumentParser(description="MIOS Gold Intelligence Platform")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_once = subparsers.add_parser("run-once", help="Run one intelligence cycle")
    run_once.add_argument("--notify", action="store_true", help="Send Discord alerts if warranted")
    run_once.add_argument("--env", default=".env", help="Optional environment file path")
    run_once.add_argument(
        "--db-path", default=None, help="Optional SQLite decision journal database path"
    )
    run_once.add_argument(
        "--mode",
        choices=["forex", "physical", "etf", "json"],
        default="json",
        help="Presentation mode for the decision output",
    )
    run_once.add_argument(
        "--committee-demo",
        action="store_true",
        help="Force real AI committee execution for hackathon demo",
    )

    run_forever = subparsers.add_parser("run-forever", help="Continuously monitor gold markets")
    run_forever.add_argument(
        "--notify", action="store_true", help="Send Discord alerts if warranted"
    )
    run_forever.add_argument("--env", default=".env", help="Optional environment file path")
    run_forever.add_argument(
        "--interval-seconds",
        type=int,
        default=None,
        help="Override config polling.run_forever_interval_seconds",
    )
    run_forever.add_argument(
        "--db-path", default=None, help="Optional SQLite decision journal database path"
    )

    serve = subparsers.add_parser("serve", help="Serve the local dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--env", default=".env", help="Optional environment file path")

    export_dashboard = subparsers.add_parser(
        "export-dashboard", help="Write standalone HTML dashboard"
    )
    export_dashboard.add_argument("--output", default="data/dashboard.html")

    backtest = subparsers.add_parser(
        "backtest", help="Backtest the full decision stack on recent gold bars"
    )
    backtest.add_argument("--lookback", type=int, default=60)
    backtest.add_argument("--horizon", type=int, default=5)
    backtest.add_argument("--env", default=".env", help="Optional environment file path")

    price = subparsers.add_parser("price", help="Show the current gold spot price")
    price.add_argument("--env", default=".env", help="Optional environment file path")

    args = parser.parse_args()

    if args.command == "run-once":
        _configure_logging()
        _load_env_file(Path(args.env))
        if args.committee_demo:
            os.environ["MIOS_COMMITTEE_DEMO"] = "1"
        orchestrator = _build_orchestrator(enable_notifications=args.notify, db_path=args.db_path)
        result = orchestrator.run_once(send_notifications=args.notify)
        if hasattr(args, "mode") and args.mode != "json":
            _print_mode_output(result, args.mode)
        else:
            print(result.decision.model_dump_json(indent=2))
        return

    if args.command == "run-forever":
        _configure_logging()
        _load_env_file(Path(args.env))
        platform_config = load_platform_config(DEFAULT_CONFIG_DIR / "platform.json")
        interval_seconds = (
            args.interval_seconds
            if args.interval_seconds is not None
            else platform_config.polling.run_forever_interval_seconds
        )
        orchestrator = _build_orchestrator(enable_notifications=args.notify, db_path=args.db_path)
        runner = ContinuousRunner(
            lambda: orchestrator.run_once(send_notifications=args.notify),
            interval_seconds=interval_seconds,
            logger=logging.getLogger("mios.run_forever"),
        )

        def request_shutdown(_signum: int, _frame: object) -> None:
            logging.getLogger("mios.run_forever").info("Shutdown requested")
            runner.request_stop()

        signal.signal(signal.SIGINT, request_shutdown)
        signal.signal(signal.SIGTERM, request_shutdown)
        logging.getLogger("mios.run_forever").info(
            "Starting MIOS continuous monitoring at %s second intervals",
            interval_seconds,
        )
        runner.run()
        logging.getLogger("mios.run_forever").info("MIOS continuous monitoring stopped")
        return

    if args.command == "serve":
        _configure_logging()
        _load_env_file(Path(args.env))
        journal = _build_journal(None)
        paper_repository = JsonPaperTradingRepository(DEFAULT_DATA_DIR / "paper_trading.json")
        serve_dashboard(
            journal,
            host=args.host,
            port=args.port,
            paper_trading_repository=paper_repository,
        )
        return

    if args.command == "export-dashboard":
        write_static_dashboard(args.output)
        print(Path(args.output).resolve())
        return

    if args.command == "price":
        _load_env_file(Path(args.env))
        result = GoldPriceService(UrlLibHttpClient()).fetch_quote()
        if result.status.value == "SUCCESS" and result.data is not None:
            print(
                f"Gold spot: {result.data.price} USD via {result.data.provider.value} "
                f"({result.data.timestamp.isoformat()})"
            )
        else:
            print(f"Gold price unavailable: {result.error}")
        return

    if args.command == "backtest":
        _configure_logging()
        _load_env_file(Path(args.env))
        platform_config = load_platform_config(DEFAULT_CONFIG_DIR / "platform.json")
        decision_config = load_decision_engine_config(DEFAULT_CONFIG_DIR / "decision_engine.json")
        provider_runtime = build_provider_runtime(platform_config)
        snapshot = asyncio.run(provider_runtime.collector.collect())[0]
        bars = snapshot.bars
        twelve_config = platform_config.providers[DataProviderId.TWELVE_DATA]

        async def _fetch_history() -> tuple:
            historical = await TwelveDataProvider(
                twelve_config, UrlLibHttpClient()
            ).gold_ohlc(Timeframe.ONE_HOUR, output_size=2000)
            return historical.status, historical.data

        status, historical_bars = asyncio.run(_fetch_history())
        if status.value == "SUCCESS" and historical_bars:
            bars = historical_bars
        result = BacktestingEngine(decision_config).run(
            bars=bars, lookback=args.lookback, horizon=args.horizon
        )
        print(
            f"Backtest: {len(result.samples)} windows | "
            f"{result.action_count} actionable | {result.wait_count} waits | "
            f"directional hit rate {result.directional_hit_rate * 100:.1f}%"
        )
        return


def _build_journal(db_path: str | None) -> DecisionJournalRepository:
    if db_path:
        return SqliteDecisionJournalRepository(Path(db_path))
    database_config = _load_database_config()
    if database_config.get("decision_journal_backend") == "sqlite":
        return SqliteDecisionJournalRepository(
            Path(database_config.get("sqlite_path", "data/mios.db"))
        )
    return JsonDecisionJournalRepository(DEFAULT_DATA_DIR / "decision_journal.json")


def _load_database_config() -> dict:
    import json

    path = DEFAULT_CONFIG_DIR / "database.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _build_orchestrator(
    enable_notifications: bool, db_path: str | None = None
) -> GoldIntelligenceOrchestrator:
    platform_config = load_platform_config(DEFAULT_CONFIG_DIR / "platform.json")
    decision_config = load_decision_engine_config(DEFAULT_CONFIG_DIR / "decision_engine.json")
    provider_runtime = build_provider_runtime(platform_config)
    research_desk = _build_research_desk(platform_config)
    ai_agent = _build_ai_agent(platform_config)
    journal = _build_journal(db_path)
    paper_trading_engine = PaperTradingEngine(
        JsonPaperTradingRepository(DEFAULT_DATA_DIR / "paper_trading.json")
    )
    notification_engine = None
    if enable_notifications:
        notification_config = load_notification_config(
            DEFAULT_CONFIG_DIR / "notifications.discord.json"
        )
        notification_engine = NotificationEngine(
            publisher=DiscordWebhookPublisher(notification_config.discord),
            state_repository=JsonNotificationStateRepository(
                DEFAULT_DATA_DIR / "notification_state.json"
            ),
            config=notification_config,
        )
    return GoldIntelligenceOrchestrator(
        ingestion_clients=IngestionClients(),
        decision_config=decision_config,
        decision_journal=journal,
        notification_engine=notification_engine,
        market_data_collector=provider_runtime.collector,
        news_engine=NewsIntelligenceEngine(
            ai_agent=ai_agent,
            ai_reasoning_enabled=platform_config.ai_reasoning_enabled,
        ),
        geopolitical_engine=GeopoliticalIntelligenceEngine(
            ai_agent=ai_agent,
            ai_reasoning_enabled=platform_config.ai_reasoning_enabled,
        ),
        paper_trading_engine=paper_trading_engine,
        research_desk=research_desk,
        gold_price_service=GoldPriceService(UrlLibHttpClient()),
        event_narrative_pipeline=EventNarrativePipeline(),
    )


def _build_ai_agent(platform_config: PlatformConfig) -> GroqNewsAnalystAgent | None:
    if not platform_config.ai_reasoning_enabled:
        return None
    return GroqNewsAnalystAgent(
        http_client=UrlLibHttpClient(),
        groq_config=platform_config.providers[DataProviderId.GROQ],
        gemini_config=platform_config.providers[DataProviderId.GEMINI],
        opencode_config=platform_config.providers[DataProviderId.OPENCODE],
        ollama_config=platform_config.providers[DataProviderId.OLLAMA],
        reasoning_config=platform_config.ai_reasoning,
        validator=AIJsonValidator(),
    )


def _build_research_desk(platform_config: PlatformConfig) -> AIResearchDesk | None:
    research_config = load_ai_research_config(DEFAULT_CONFIG_DIR / "ai_research.json")
    if not platform_config.ai_reasoning_enabled or not research_config.enabled:
        return None
    return AIResearchDesk(
        config=research_config,
        client=LLMJsonClient(
            http_client=UrlLibHttpClient(),
            groq_config=platform_config.providers[DataProviderId.GROQ],
            gemini_config=platform_config.providers[DataProviderId.GEMINI],
            opencode_config=platform_config.providers[DataProviderId.OPENCODE],
            ollama_config=platform_config.providers[DataProviderId.OLLAMA],
            reasoning_config=platform_config.ai_reasoning,
        ),
        validator=AIJsonValidator(),
        knowledge_retriever=KnowledgeRetriever(JsonKnowledgeRepository(DEFAULT_KNOWLEDGE_DIR)),
    )


def _make_console_encoding_safe() -> None:
    """Windows consoles default to cp1252 and crash printing non-ASCII decision
    text (e.g. typographic quotes). Replace errors instead of raising, and prefer
    UTF-8 when the stream supports it."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _configure_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=(
            logging.StreamHandler(),
            RotatingFileHandler(
                LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            ),
        ),
    )
    logging.getLogger("mios.providers").setLevel(logging.WARNING)
    logging.getLogger("mios.providers").propagate = True


def _print_mode_output(result, adapter_name: str) -> None:
    print(f"\n{'='*60}")
    print(f" MIOS v5.0 - {adapter_name.upper()} DECISION ")
    print(f"{'='*60}\n")
    
    committee_direction = "WAIT"
    committee_conf = 0
    disagreements = []
    
    if result.decision.research_desk_report and result.decision.research_desk_report.committee_report:
        cr = result.decision.research_desk_report.committee_report
        committee_direction = cr.final_recommendation.name
        committee_conf = cr.confidence
        disagreements = cr.disagreements

    print("COMMITTEE OPINION:")
    print(f"  {committee_direction} - {committee_conf}%")
    for dis in disagreements[:2]:
        print(f"  * {dis}")
    print("")

    print("RISK / OPPORTUNITY FILTER:")
    for risk in result.decision.risk_summary[:2]:
        print(f"  * {risk.risk} ({risk.severity.name})")
    
    trace = result.decision.decision_trace
    if trace:
        for penal in trace.confidence_attribution:
            if penal.contribution < 0:
                print(f"  * {penal.source}: {penal.rationale} ({penal.contribution}%)")

    unified = result.unified_decision
    
    from app.infrastructure.config_loader import load_decision_engine_config
    from app.application.execution_policy import ModeExecutionPolicy
    config = load_decision_engine_config("config/decision_engine.json")
    policy = ModeExecutionPolicy(config.thresholds)
    
    policy_result = policy.evaluate(adapter_name, result.decision.confidence, unified.market_bias, result.decision, result.bundle)
    
    final_action_name = "NEUTRAL" if not policy_result.actionable else result.decision.recommendation.name

    print(f"Directional Bias: {unified.market_bias.name}")
    if result.decision.pullback_risk_report:
        pb = result.decision.pullback_risk_report
        print(f"Pullback Risk: {pb.level} ({pb.score}/100)")
        if pb.drivers:
            print("\nTop Pullback Risks:")
            for d in pb.drivers:
                print(f"- {d}")
    print("")

    print(f"FINAL MIOS ACTION:")
    print(f"  {final_action_name} (Confidence: {result.decision.confidence}%)\n")
    print("-" * 60)
    
    print(f"\n--- {adapter_name.capitalize()} Mode Output ---")
    
    # ALWAYS DISPLAY EXPECTED MOVE
    move_val = 0
    move_str = "N/A"
    if result.decision.expected_move and result.decision.expected_move.min_usd is not None:
        move_val = float(result.decision.expected_move.min_usd)
        move_dir = result.decision.expected_move.direction
        if move_dir in ("UP", "LONG", "BULLISH"):
            move_str = f"+${move_val:g}"
        elif move_dir in ("DOWN", "SHORT", "BEARISH"):
            move_str = f"-${move_val:g}"
        else:
            move_str = f"${move_val:g}"
            
    is_wait = not policy_result.actionable or unified.market_bias.name == "NEUTRAL"
    if is_wait:
        print(f"Reference Price: {result.spot_price}")
        print(f"Expected Move: {move_str}")
        print("Action: WAIT")
        if not policy_result.actionable:
            print(f"Reason: {policy_result.reason}")
    else:
        print(f"Entry: {result.spot_price}")
        print(f"Expected Move: {move_str}")
    
    if adapter_name == "physical":
        from app.application.adapters.physical import PhysicalGoldAdapter
        adapted = PhysicalGoldAdapter().adapt(unified, is_actionable=not is_wait)
        if not is_wait:
            print(f"Action     : {adapted.action}")
        print(f"Allocation : {adapted.allocation_guidance}")
        print(f"Conviction : {adapted.conviction}")
        print(f"Horizon    : {adapted.horizon}")
        print(f"\nThesis:\n{adapted.thesis}")
    elif adapter_name == "forex":
        from app.application.adapters.forex import ForexAdapter
        spot = result.spot_price
        adapted = ForexAdapter().adapt(unified, spot=spot)
        if not is_wait:
            print(f"Take Profit : {adapted.take_profit}")
            print(f"Stop Loss   : {adapted.stop_loss}")
        print(f"Risk        : {adapted.risk}")
        print(f"Horizon     : {adapted.horizon}")
        print(f"\nReasoning:\n{adapted.reasoning}")
    elif adapter_name == "etf":
        from app.application.adapters.etf import GoldETFAdapter
        adapted = GoldETFAdapter().adapt(unified, is_actionable=not is_wait)
        if not is_wait:
            print(f"Action     : {adapted.action}")
        print(f"Vehicle    : {adapted.vehicle_guidance}")
        print(f"Flows      : {adapted.flow_context}")
        print(f"Allocation : {adapted.allocation_guidance}")
        print(f"\nThesis:\n{adapted.thesis}")
        
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()

