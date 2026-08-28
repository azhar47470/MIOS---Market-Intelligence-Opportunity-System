import asyncio
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from pydantic import Field

from app.ai.research_desk import AIResearchDesk
from app.application.adapters.unified import UnifiedDecisionBuilder
from app.application.decision_config import DecisionEngineConfig
from app.application.decision_journal import DecisionJournalRepository
from app.application.engines.decision_engine import (
    DecisionEngine,
    InvestmentScoringEngine,
    OpportunityFilter,
)
from app.application.engines.fundamental_engine import FundamentalIntelligenceEngine
from app.application.engines.geopolitical_engine import GeopoliticalIntelligenceEngine
from app.application.engines.institutional_engine import InstitutionalIntelligenceEngine
from app.application.engines.news_engine import NewsIntelligenceEngine
from app.application.engines.regime_engine import MarketRegimeEngine
from app.application.engines.technical_engine import TechnicalIntelligenceEngine
from app.application.engines.pullback_risk_engine import PullbackRiskEngine, report_to_evidence
from app.application.event_bus import EventBus
from app.application.events.detector import EventDetector
from app.application.events.pipeline import EventNarrativePipeline
from app.application.gold_price_service import GoldPriceService
from app.application.market_data_collector import RepositoryBackedMarketDataCollector
from app.application.notification_engine import NotificationEngine
from app.domain.ai import AgentRole
from app.domain.common import ContractStatus, DomainModel, ProviderResult
from app.domain.enums import DeliveryStatus, NotificationPriority
from app.domain.events import EventPriority, MarketUpdatedEvent, RecommendationChangedEvent
from app.domain.intelligence import (
    AnalysisBundle,
    DecisionContext,
    DecisionReport,
    EngineBreakdown,
    EngineId,
    MarketDataSnapshot,
)
from app.domain.decisions import UnifiedDecision
from app.domain.market_data import (
    CotPositioningSnapshot,
    EconomicCalendarEvent,
    EtfFlowSnapshot,
    MacroSeriesObservation,
    MarketQuote,
    MarketSymbol,
    NewsArticle,
    OhlcBar,
    Timeframe,
)
from app.domain.notification_models import (
    EvidenceItem,
    ExpectedMove,
    PriceLevel,
    RecommendationSnapshot,
    RiskItem,
    SupportResistanceLevels,
)
from app.ingestion.factory import IngestionClients
from app.paper_trading.engine import PaperTradingEngine


class OrchestratorRunResult(DomainModel):
    decision: DecisionReport
    provider_statuses: dict[str, ContractStatus] = Field(default_factory=dict)
    notification_status: DeliveryStatus | None = None
    paper_trading: dict[str, object] | None = None
    unified_decision: UnifiedDecision | None = None
    bundle: AnalysisBundle | None = None
    spot_price: float | None = None


class GoldIntelligenceOrchestrator:
    def __init__(
        self,
        decision_config: DecisionEngineConfig,
        decision_journal: DecisionJournalRepository,
        notification_engine: NotificationEngine | None = None,
        event_bus: EventBus | None = None,
        market_data_collector: RepositoryBackedMarketDataCollector | None = None,
        news_engine: NewsIntelligenceEngine | None = None,
        geopolitical_engine: GeopoliticalIntelligenceEngine | None = None,
        paper_trading_engine: PaperTradingEngine | None = None,
        research_desk: AIResearchDesk | None = None,
        ingestion_clients: IngestionClients | None = None,
        gold_price_service: GoldPriceService | None = None,
        event_narrative_pipeline: EventNarrativePipeline | None = None,
        unified_decision_builder: UnifiedDecisionBuilder | None = None,
    ) -> None:
        self._ingestion_clients = ingestion_clients or IngestionClients()
        self._decision_journal = decision_journal
        self._notification_engine = notification_engine
        self._event_bus = event_bus
        self._market_data_collector = market_data_collector
        self._paper_trading_engine = paper_trading_engine
        self._research_desk = research_desk
        self._gold_price_service = gold_price_service
        self._event_narrative_pipeline = event_narrative_pipeline
        self._unified_decision_builder = unified_decision_builder or UnifiedDecisionBuilder()
        self._technical_engine = TechnicalIntelligenceEngine(
            stale_candle_threshold_minutes=decision_config.thresholds.stale_candle_threshold_minutes
        )
        self._fundamental_engine = FundamentalIntelligenceEngine()
        self._institutional_engine = InstitutionalIntelligenceEngine()
        self._news_engine = news_engine or NewsIntelligenceEngine()
        self._geopolitical_engine = geopolitical_engine or GeopoliticalIntelligenceEngine()
        self._regime_engine = MarketRegimeEngine(decision_config.weights)
        self._pullback_risk_engine = PullbackRiskEngine()
        self._opportunity_filter = OpportunityFilter(decision_config)
        self._scoring_engine = InvestmentScoringEngine()
        self._decision_engine = DecisionEngine(decision_config)

    def run_once(self, send_notifications: bool = False) -> OrchestratorRunResult:
        market_data, provider_statuses = self._collect_market_data()
        quote = market_data.quote
        if quote is None and self._gold_price_service is not None:
            quote_result = self._gold_price_service.fetch_quote()
            if quote_result.status == ContractStatus.SUCCESS and quote_result.data is not None:
                quote = quote_result.data
        if self._event_narrative_pipeline is not None:
            articles = market_data.news_articles + market_data.geopolitical_articles
            events, narratives = self._event_narrative_pipeline.run(articles)
            market_data = market_data.model_copy(
                update={"events": events, "narratives": narratives}
            )
        self._publish_market_updated(market_data, provider_statuses)
        engine_runtimes: dict[EngineId, int] = {}
        started_at = perf_counter()
        technical = self._technical_engine.analyze(market_data.bars)
        engine_runtimes[EngineId.TECHNICAL] = _elapsed_ms(started_at)
        started_at = perf_counter()
        fundamental = self._fundamental_engine.analyze(
            market_data.dxy_observations,
            market_data.economic_events,
            market_data.provider_errors,
            market_data.macro_observations,
        )
        engine_runtimes[EngineId.FUNDAMENTAL] = _elapsed_ms(started_at)
        started_at = perf_counter()
        institutional = self._institutional_engine.analyze(
            market_data.cot_positioning,
            market_data.gld_flow,
            market_data.provider_errors,
        )
        engine_runtimes[EngineId.INSTITUTIONAL] = _elapsed_ms(started_at)
        started_at = perf_counter()
        news = self._news_engine.analyze(market_data.news_articles)
        engine_runtimes[EngineId.NEWS] = _elapsed_ms(started_at)
        started_at = perf_counter()
        geopolitical = self._geopolitical_engine.analyze(market_data.geopolitical_articles)
        engine_runtimes[EngineId.GEOPOLITICAL] = _elapsed_ms(started_at)
        started_at = perf_counter()
        regime = self._regime_engine.analyze(technical, fundamental, news, geopolitical)
        engine_runtimes[EngineId.MARKET_REGIME] = _elapsed_ms(started_at)
        pullback_report = self._pullback_risk_engine.analyze(market_data.bars, regime)
        pullback_evidence = report_to_evidence(pullback_report)
        technical = technical.model_copy(update={"evidence": technical.evidence + tuple(pullback_evidence)})

        analysis = AnalysisBundle(
            market_data=market_data,
            technical=technical,
            fundamental=fundamental,
            news=news,
            geopolitical=geopolitical,
            institutional=institutional,
            regime=regime,
        )
        research_desk_report = (
            self._research_desk.analyze(analysis) if self._research_desk is not None else None
        )
        if research_desk_report is not None:
            reports_by_role = {
                report.role: report for report in research_desk_report.analyst_reports
            }
            # The desk's specialist reports are deterministic today (no per-specialist LLM),
            # so re-running the engines would only repeat their own direct AI calls. Only
            # re-run when a specialist really is an AI synthesis the engine should prefer.
            news_report = reports_by_role.get(AgentRole.NEWS_ANALYST)
            if news_report is not None and news_report.provider != "deterministic_fallback":
                started_at = perf_counter()
                news = self._news_engine.analyze(market_data.news_articles, news_report)
                engine_runtimes[EngineId.NEWS] = _elapsed_ms(started_at)
            geopolitical_report = reports_by_role.get(AgentRole.GEOPOLITICAL_ANALYST)
            if (
                geopolitical_report is not None
                and geopolitical_report.provider != "deterministic_fallback"
            ):
                started_at = perf_counter()
                geopolitical = self._geopolitical_engine.analyze(
                    market_data.geopolitical_articles, geopolitical_report
                )
                engine_runtimes[EngineId.GEOPOLITICAL] = _elapsed_ms(started_at)
            if (
                news_report is not None and news_report.provider != "deterministic_fallback"
            ) or (
                geopolitical_report is not None
                and geopolitical_report.provider != "deterministic_fallback"
            ):
                started_at = perf_counter()
                regime = self._regime_engine.analyze(technical, fundamental, news, geopolitical)
                engine_runtimes[EngineId.MARKET_REGIME] = _elapsed_ms(started_at)
                analysis = AnalysisBundle(
                    market_data=market_data,
                    technical=technical,
                    fundamental=fundamental,
                    news=news,
                    geopolitical=geopolitical,
                    institutional=institutional,
                    regime=regime,
                )

        opportunity = self._opportunity_filter.assess(analysis)
        investment_score = self._scoring_engine.score(analysis)
        context = DecisionContext(
            market_data=market_data,
            technical=technical,
            fundamental=fundamental,
            news=news,
            geopolitical=geopolitical,
            institutional=institutional,
            regime=regime,
            opportunity=opportunity,
            investment_score=investment_score,
            research_desk_report=research_desk_report,
        )
        decision = self._decision_engine.decide(context)
        
        unified_decision = self._unified_decision_builder.build(
            decision=decision,
            bundle=analysis,
            research=research_desk_report,
        )

        from app.application.execution_policy import ModeExecutionPolicy
        from app.infrastructure.config_loader import load_decision_engine_config
        config = load_decision_engine_config("config/decision_engine.json")
        policy = ModeExecutionPolicy(config.thresholds)
        
        move_val = 0
        move_str = "N/A"
        if decision.expected_move and decision.expected_move.min_usd is not None:
            move_val = float(decision.expected_move.min_usd)
            move_dir = decision.expected_move.direction
            if move_dir in ("UP", "LONG", "BULLISH"):
                move_str = f"+${move_val:g}"
            elif move_dir in ("DOWN", "SHORT", "BEARISH"):
                move_str = f"-${move_val:g}"
            else:
                move_str = f"${move_val:g}"
                
        spot_price_float = float(quote.price) if quote else 0.0

        from app.application.adapters.physical import PhysicalGoldAdapter
        from app.application.adapters.forex import ForexAdapter
        from app.application.adapters.etf import GoldETFAdapter
        from app.domain.intelligence import ModePolicyPresentation

        adapters = {
            "physical": PhysicalGoldAdapter(),
            "forex": ForexAdapter(),
            "etf": GoldETFAdapter(),
        }

        mode_results = []
        for mode, adapter in adapters.items():
            pol_res = policy.evaluate(mode, decision.confidence, unified_decision.market_bias, decision, analysis)
            is_wait = not pol_res.actionable or unified_decision.market_bias.name == "NEUTRAL"
            
            entry = None
            tp = None
            sl = None
            allocation = None
            risk = None
            horizon = None
            action = "WAIT" if is_wait else unified_decision.market_bias.name

            if mode == "physical":
                adapted = adapter.adapt(unified_decision, is_actionable=not is_wait)
                if not is_wait:
                    action = adapted.action
                    entry = f"{spot_price_float}"
                allocation = adapted.allocation_guidance
                horizon = adapted.horizon
            elif mode == "forex":
                adapted = adapter.adapt(unified_decision, spot=spot_price_float, is_actionable=not is_wait)
                if not is_wait:
                    entry = f"{spot_price_float}"
                    tp = adapted.take_profit
                    sl = adapted.stop_loss
                risk = adapted.risk
                horizon = adapted.horizon
            elif mode == "etf":
                adapted = adapter.adapt(unified_decision, is_actionable=not is_wait)
                if not is_wait:
                    action = adapted.action
                    entry = f"{spot_price_float}"
                allocation = adapted.allocation_guidance
                horizon = adapted.horizon

            mode_results.append(ModePolicyPresentation(
                mode=mode,
                actionable=pol_res.actionable,
                action=action,
                reason=pol_res.reason,
                is_wait=is_wait,
                confidence=decision.confidence,
                expected_move=move_str,
                entry=str(entry) if entry is not None else None,
                take_profit=str(tp) if tp is not None else None,
                stop_loss=str(sl) if sl is not None else None,
                allocation=str(allocation) if allocation is not None else None,
                risk=str(risk) if risk is not None else None,
                horizon=str(horizon) if horizon is not None else None
            ))

        telemetry = {
            "sources": len(provider_statuses),
            "articles": len(analysis.market_data.news_articles) + len(analysis.market_data.geopolitical_articles),
            "events": len(analysis.market_data.events),
            "narratives": len(analysis.market_data.narratives),
            "engines": len(engine_runtimes),
            "modes": len(mode_results),
            "committee_members": len(research_desk_report.analyst_reports) if research_desk_report else 0
        }

        decision = decision.model_copy(
            update={
                "engine_breakdown": _engine_breakdown(analysis, engine_runtimes),
                "provider_statuses": provider_statuses,
                "pullback_risk_report": pullback_report,
                "mode_policy_results": tuple(mode_results),
                "spot_price": spot_price_float,
                "pipeline_telemetry": telemetry,
            }
        )
        previous_decision = self._decision_journal.latest()
        self._decision_journal.append(decision)
        self._publish_recommendation_changed(previous_decision, decision)
        notification_status = None
        if send_notifications and self._notification_engine is not None:
            outcome = self._notification_engine.process_recommendation(
                _to_recommendation_snapshot(decision)
            )
            notification_status = outcome.status
        paper_trading = None
        if self._paper_trading_engine is not None and quote is not None:
            active_narratives = tuple(
                narrative.name
                for narrative in analysis.market_data.narratives
                if narrative.strength > 0.3
            )
            self._paper_trading_engine.update(decision, quote.price, active_narratives)
            paper_trading = self._paper_trading_engine.summary()
        return OrchestratorRunResult(
            decision=decision,
            provider_statuses=provider_statuses,
            notification_status=notification_status,
            paper_trading=paper_trading,
            unified_decision=unified_decision,
            spot_price=float(quote.price) if quote else None,
            bundle=analysis,
        )

    def _collect_market_data(self) -> tuple[MarketDataSnapshot, dict[str, ContractStatus]]:
        if self._market_data_collector is not None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop is not None and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, self._market_data_collector.collect())
                    return future.result()
            else:
                return asyncio.run(self._market_data_collector.collect())

        # Fallback path using ingestion_clients for compatibility with existing unit tests
        statuses: dict[str, ContractStatus] = {}
        provider_errors: dict[str, str] = {}
        quote: MarketQuote | None = None
        bars: tuple[OhlcBar, ...] = ()
        dxy_observations: tuple[MacroSeriesObservation, ...] = ()
        economic_events: tuple[EconomicCalendarEvent, ...] = ()
        news_articles: tuple[NewsArticle, ...] = ()
        geopolitical_articles: tuple[NewsArticle, ...] = ()
        cot_positioning: tuple[CotPositioningSnapshot, ...] = ()
        gld_flow: EtfFlowSnapshot | None = None

        if self._ingestion_clients.twelve_data is not None:
            quote_result = self._ingestion_clients.twelve_data.get_quote(MarketSymbol.XAU_USD)
            statuses["twelve_data_quote"] = quote_result.status
            _capture_provider_error(provider_errors, "gold_price", quote_result.error)
            quote = _data_or_none(quote_result)
            bars_result = self._ingestion_clients.twelve_data.get_ohlc(
                MarketSymbol.XAU_USD, Timeframe.ONE_HOUR, output_size=100
            )
            statuses["twelve_data_ohlc"] = bars_result.status
            _capture_provider_error(provider_errors, "gold_bars", bars_result.error)
            bars = _data_or_default(bars_result, ())
            if quote is None and bars:
                latest_bar = max(bars, key=lambda bar: bar.timestamp)
                quote = MarketQuote(
                    symbol=MarketSymbol.XAU_USD,
                    provider_symbol=latest_bar.provider_symbol,
                    price=latest_bar.close,
                    timestamp=latest_bar.timestamp,
                    provider=latest_bar.provider,
                )
        if self._ingestion_clients.fred is not None:
            dxy_result = self._ingestion_clients.fred.get_series_observations("DTWEXBGS")
            statuses["fred_dxy"] = dxy_result.status
            _capture_provider_error(provider_errors, "dxy", dxy_result.error)
            dxy_observations = _data_or_default(dxy_result, ())
        if self._ingestion_clients.newsapi is not None:
            news_result = self._ingestion_clients.newsapi.get_articles("gold OR XAU/USD")
            statuses["newsapi_gold"] = news_result.status
            _capture_provider_error(provider_errors, "news", news_result.error)
            news_articles = _data_or_default(news_result, ())
        if self._ingestion_clients.gdelt is not None:
            geopolitical_result = self._ingestion_clients.gdelt.get_articles(
                'gold OR "central bank" OR sanctions OR war'
            )
            statuses["gdelt_geopolitics"] = geopolitical_result.status
            _capture_provider_error(provider_errors, "gdelt", geopolitical_result.error)
            geopolitical_articles = _data_or_default(geopolitical_result, ())
        if self._ingestion_clients.cftc_cot is not None:
            cot_result = self._ingestion_clients.cftc_cot.get_gold_cot_positioning()
            statuses["cftc_cot"] = cot_result.status
            _capture_provider_error(provider_errors, "cot", cot_result.error)
            cot_positioning = _data_or_default(cot_result, ())
        if self._ingestion_clients.spdr_gld is not None:
            gld_result = self._ingestion_clients.spdr_gld.get_latest_gld_flow()
            statuses["spdr_gld"] = gld_result.status
            _capture_provider_error(provider_errors, "gld", gld_result.error)
            gld_flow = _data_or_none(gld_result)

        return (
            MarketDataSnapshot(
                quote=quote,
                bars=bars,
                dxy_observations=dxy_observations,
                economic_events=economic_events,
                news_articles=news_articles,
                geopolitical_articles=geopolitical_articles,
                cot_positioning=cot_positioning,
                gld_flow=gld_flow,
                provider_errors=provider_errors,
                collected_at=datetime.now(UTC),
            ),
            statuses,
        )

    def _publish_market_updated(
        self,
        market_data: MarketDataSnapshot,
        provider_statuses: dict[str, ContractStatus],
    ) -> None:
        if self._event_bus is None:
            return
        self._event_bus.publish(
            MarketUpdatedEvent(
                event_id=f"market-{market_data.collected_at.isoformat()}",
                priority=EventPriority.NORMAL,
                payload={
                    "collected_at": market_data.collected_at.isoformat(),
                    "quote_available": market_data.quote is not None,
                    "bar_count": len(market_data.bars),
                    "provider_statuses": {
                        key: value.value for key, value in provider_statuses.items()
                    },
                },
            )
        )

    def _publish_recommendation_changed(
        self,
        previous_decision: DecisionReport | None,
        decision: DecisionReport,
    ) -> None:
        if self._event_bus is None:
            return
        if (
            previous_decision is not None
            and previous_decision.recommendation == decision.recommendation
        ):
            return
        self._event_bus.publish(
            RecommendationChangedEvent(
                event_id=f"recommendation-{decision.recommendation_id}",
                priority=EventPriority.HIGH,
                payload={
                    "recommendation_id": decision.recommendation_id,
                    "previous": (
                        previous_decision.recommendation.value
                        if previous_decision is not None
                        else None
                    ),
                    "current": decision.recommendation.value,
                    "confidence": decision.confidence,
                    "investment_score": decision.investment_score,
                },
            )
        )


def _data_or_none[T](result: ProviderResult[T]) -> T | None:
    if result.status == ContractStatus.SUCCESS:
        return result.data
    return None


def _data_or_default[T](result: ProviderResult[T], default: T) -> T:
    if result.status == ContractStatus.SUCCESS and result.data is not None:
        return result.data
    return default


def _capture_provider_error(errors: dict[str, str], key: str, error: str | None) -> None:
    if error:
        errors[key] = error


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def _engine_breakdown(
    analysis: AnalysisBundle,
    runtimes: dict[EngineId, int] | None = None,
) -> tuple[EngineBreakdown, ...]:
    results = (
        analysis.technical,
        analysis.fundamental,
        analysis.institutional,
        analysis.news,
        analysis.geopolitical,
        analysis.regime,
    )
    return tuple(
        EngineBreakdown(
            engine=result.engine,
            status=result.status,
            score=result.score,
            confidence=result.confidence.value,
            runtime_ms=(runtimes or {}).get(result.engine, 0),
            evidence=result.evidence,
        )
        for result in results
    )


def _to_recommendation_snapshot(report: DecisionReport) -> RecommendationSnapshot:
    return RecommendationSnapshot(
        recommendation_id=report.recommendation_id,
        recommendation=report.recommendation,
        investment_score=report.investment_score,
        confidence=report.confidence,
        expected_move=ExpectedMove(
            direction=report.expected_move.direction,
            min_usd=report.expected_move.min_usd,
            max_usd=report.expected_move.max_usd,
            summary=report.expected_move.summary,
        ),
        expected_holding_period=report.expected_holding_period,
        market_regime=report.market_regime.value,
        supporting_evidence=tuple(
            EvidenceItem(
                category=evidence.category,
                description=evidence.description,
                strength=evidence.strength.value,
                confidence=evidence.confidence,
                source=evidence.source,
            )
            for evidence in report.supporting_evidence
        ),
        contradicting_evidence=tuple(
            EvidenceItem(
                category=evidence.category,
                description=evidence.description,
                strength=evidence.strength.value,
                confidence=evidence.confidence,
                source=evidence.source,
            )
            for evidence in report.contradicting_evidence
        ),
        risk_summary=tuple(
            RiskItem(
                summary=risk.risk,
                severity=_notification_priority_from_risk(risk.severity.value),
                probability=risk.probability,
            )
            for risk in report.risk_summary
        ),
        invalidation_conditions=report.invalidation_conditions,
        support_resistance=SupportResistanceLevels(
            support=tuple(
                PriceLevel(label=level.label, price=level.price, rationale=level.rationale)
                for level in report.support_resistance.support
            ),
            resistance=tuple(
                PriceLevel(label=level.label, price=level.price, rationale=level.rationale)
                for level in report.support_resistance.resistance
            ),
        ),
        timestamp=report.timestamp,
    )


def _notification_priority_from_risk(severity: str) -> NotificationPriority:
    if severity == "CRITICAL":
        return NotificationPriority.CRITICAL
    if severity == "HIGH":
        return NotificationPriority.HIGH
    if severity == "MEDIUM":
        return NotificationPriority.NORMAL
    if severity == "LOW":
        return NotificationPriority.LOW
    import logging
    logging.getLogger("mios.orchestrator").warning(
        "Unexpected risk severity value %r — defaulting to NORMAL", severity
    )
    return NotificationPriority.NORMAL
