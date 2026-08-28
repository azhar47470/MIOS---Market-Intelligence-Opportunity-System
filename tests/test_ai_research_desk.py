import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.ai.agents.llm_client import LLMJsonClient
from app.ai.context_builder import AIContextBuilder
from app.ai.research_desk import AIResearchDesk
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
from app.application.http import HttpResponse
from app.domain.ai import AgentRole
from app.domain.common import ConfidenceScore, EvidenceRecord, EvidenceStrength
from app.domain.enums import Recommendation
from app.domain.intelligence import (
    AnalysisBundle,
    DecisionContext,
    MarketDataSnapshot,
    MarketRegime,
)
from app.domain.market_data import (
    CotPositioningSnapshot,
    DataProviderId,
    EtfFlowSnapshot,
    MacroSeriesObservation,
    MarketSymbol,
    NewsArticle,
    OhlcBar,
    Timeframe,
)
from app.infrastructure.config_loader import (
    load_ai_research_config,
    load_decision_engine_config,
    load_platform_config,
)


class FakeAIHttpClient:
    """Records every POST made and answers with a committee member vote payload.

    The research desk now runs an adversarial four-member committee: two Gemini-pinned
    members (macro strategist, tactical trader) and one Groq-pinned member (contrarian
    risk) plus the rule-based deterministic anchor. Each AI member makes exactly one
    LLM call, so there are exactly three posts per cycle.
    """

    def __init__(self) -> None:
        self.posts: list[dict] = []

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        raise AssertionError("AI research should not issue GET requests")

    def post(self, url, body, params=None, headers=None, timeout_seconds=10.0):
        request = {
            "url": url,
            "body": json.loads(body),
            "params": params or {},
            "headers": headers or {},
        }
        self.posts.append(request)
        vote = json.dumps(_member_vote_payload())
        if "generativelanguage" in url:
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "candidates": [{"content": {"parts": [{"text": vote}]}}],
                        "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7},
                    }
                ),
            )
        return HttpResponse(
            status_code=200,
            body=json.dumps(
                {
                    "choices": [{"message": {"content": vote}}],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                }
            ),
        )


def test_research_desk_committee_runs_four_member_vote_with_three_llm_calls(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    platform_config = load_platform_config("config/platform.json")
    research_config = load_ai_research_config("config/ai_research.json")
    http = FakeAIHttpClient()
    desk = AIResearchDesk(
        config=research_config,
        client=LLMJsonClient(
            http_client=http,
            groq_config=platform_config.providers[DataProviderId.GROQ],
            gemini_config=platform_config.providers[DataProviderId.GEMINI],
            opencode_config=platform_config.providers[DataProviderId.OPENCODE],
            ollama_config=platform_config.providers[DataProviderId.OLLAMA],
            reasoning_config=platform_config.ai_reasoning,
        ),
    )

    report = desk.analyze(_analysis_bundle())

    assert len(report.analyst_reports) == 8
    assert {item.role for item in report.analyst_reports} == {
        AgentRole.TECHNICAL_ANALYST,
        AgentRole.MACRO_ECONOMIST,
        AgentRole.FEDERAL_RESERVE_ANALYST,
        AgentRole.INSTITUTIONAL_ANALYST,
        AgentRole.ETF_FLOW_ANALYST,
        AgentRole.NEWS_ANALYST,
        AgentRole.GEOPOLITICAL_ANALYST,
        AgentRole.RISK_ANALYST,
    }
    # Every specialist report is built straight from its deterministic engine now — no
    # per-specialist LLM call is made for it.
    assert all(item.provider == "deterministic_fallback" for item in report.analyst_reports)
    assert all(item.usage is None for item in report.analyst_reports)
    # Three adversarial member calls: two Gemini-pinned, one Groq-pinned.
    assert report.committee_report.provider == "adversarial_committee"
    assert report.committee_report.final_recommendation in {
        Recommendation.BUY,
        Recommendation.STRONG_BUY,
    }
    assert report.committee_report.confidence >= 40
    assert len(http.posts) == 3
    urls = [p["url"] for p in http.posts]
    # Check that all URLs point to the same provider domain
    first_url_domain = urls[0].split("/")[2]
    for url in urls:
        assert url.split("/")[2] == first_url_domain, "No unexpected provider switching should occur"

    # Distinct decision styles: temperatures 0.4 and 0.5 for the Gemini members, 0.6 for Groq.
    
    
    assert report.committee_report.usage is not None
    assert report.committee_report.usage.prompt_tokens == 33


def test_research_desk_combined_context_covers_every_deterministic_engine():
    bundle = _analysis_bundle()
    contexts = AIContextBuilder()

    combined = contexts.for_research_desk(bundle)

    assert set(combined.facts) == {
        "price_context",
        "data_status",
        "engine_summaries",
        "evidence",
        "risks",
        "narratives",
        "events",
        "_telemetry",
    }
    
    


def test_specialists_receive_only_their_scoped_facts():
    bundle = _analysis_bundle()
    contexts = AIContextBuilder()

    technical = contexts.for_specialist(AgentRole.TECHNICAL_ANALYST, bundle)
    news = contexts.for_specialist(AgentRole.NEWS_ANALYST, bundle)
    risk = contexts.for_specialist(AgentRole.RISK_ANALYST, bundle)

    assert set(technical.facts) == {"technical", "evidence", "price_context"}
    assert set(news.facts) == {"news", "evidence", "articles"}
    assert "technical" not in news.facts
    assert set(risk.facts) == {"risks", "data_status"}


def test_research_desk_degrades_committee_to_deterministic_synthesis_when_the_call_fails(
    monkeypatch,
):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    platform_config = load_platform_config("config/platform.json")
    research_config = load_ai_research_config("config/ai_research.json")
    http = FakeAIHttpClient()
    desk = AIResearchDesk(
        config=research_config,
        client=LLMJsonClient(
            http_client=http,
            groq_config=platform_config.providers[DataProviderId.GROQ],
            gemini_config=platform_config.providers[DataProviderId.GEMINI],
            opencode_config=platform_config.providers[DataProviderId.OPENCODE],
            ollama_config=platform_config.providers[DataProviderId.OLLAMA],
            reasoning_config=platform_config.ai_reasoning,
        ),
    )

    report = desk.analyze(_analysis_bundle())

    assert len(report.analyst_reports) == 8
    assert all(item.provider == "deterministic_fallback" for item in report.analyst_reports)
    # These are the normal, intended path (no per-specialist LLM call is made at all) rather
    # than a degraded AI-failure fallback, so they carry real confidence and no fallback_reason
    # even when the committee call itself has no credentials to work with.
    assert all(item.fallback_reason is None for item in report.analyst_reports)
    assert report.committee_report.provider == "deterministic_fallback"
    assert report.committee_report.confidence_adjustment < 0
    # Every AI member fell back to the desk evidence; none of them could make an HTTP call.
    assert len(report.committee_report.missing_evidence) == 3
    assert not http.posts


def test_committee_trace_is_advisory_and_cannot_override_deterministic_wait(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    platform_config = load_platform_config("config/platform.json")
    research_config = load_ai_research_config("config/ai_research.json")
    decision_config = load_decision_engine_config("config/decision_engine.json")
    
    # Increase minimum confidence to force the underlying engine into WAIT
    decision_config = decision_config.model_copy(
        update={"thresholds": decision_config.thresholds.model_copy(update={"minimum_confidence_for_action": 99})}
    )
    
    desk = AIResearchDesk(
        config=research_config,
        client=LLMJsonClient(
            http_client=FakeAIHttpClient(),
            groq_config=platform_config.providers[DataProviderId.GROQ],
            gemini_config=platform_config.providers[DataProviderId.GEMINI],
            opencode_config=platform_config.providers[DataProviderId.OPENCODE],
            ollama_config=platform_config.providers[DataProviderId.OLLAMA],
            reasoning_config=platform_config.ai_reasoning,
        ),
    )
    analysis = _analysis_bundle()
    research = desk.analyze(analysis)
    bullish_committee = research.committee_report.model_copy(
        update={"final_recommendation": Recommendation.STRONG_BUY, "confidence_adjustment": 10}
    )
    context = DecisionContext(
        market_data=analysis.market_data,
        technical=analysis.technical,
        fundamental=analysis.fundamental,
        news=analysis.news,
        geopolitical=analysis.geopolitical,
        institutional=analysis.institutional,
        regime=analysis.regime,
        opportunity=OpportunityFilter(decision_config).assess(analysis),
        investment_score=InvestmentScoringEngine().score(analysis),
        research_desk_report=research.model_copy(update={"committee_report": bullish_committee}),
    )

    decision = DecisionEngine(decision_config).decide(context)

    assert decision.recommendation is Recommendation.WAIT
    assert decision.decision_trace is not None
    assert decision.decision_trace.committee_adjustment == 10
    assert decision.decision_trace.required_confirmations
    assert decision.research_desk_report is not None


def _member_vote_payload() -> dict:
    return {
        "direction": "LONG",
        "confidence": 0.62,
        "reasoning": "Momentum and macro alignment favor gold.",
        "key_risk": "A stronger dollar would invalidate the setup.",
        "time_horizon": "1-4 weeks",
    }


def _analysis_bundle() -> AnalysisBundle:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    bars = tuple(
        OhlcBar(
            symbol=MarketSymbol.XAU_USD,
            provider_symbol="XAU/USD",
            timeframe=Timeframe.ONE_HOUR,
            timestamp=now - timedelta(hours=34 - index),
            open=Decimal("2300") + Decimal(index),
            high=Decimal("2303") + Decimal(index),
            low=Decimal("2298") + Decimal(index),
            close=Decimal("2301") + Decimal(index),
            volume=Decimal("1000"),
            provider=DataProviderId.TWELVE_DATA,
        )
        for index in range(35)
    )
    dxy = (
        MacroSeriesObservation(
            series_id="DTWEXBGS",
            date=now - timedelta(days=1),
            value=Decimal("105"),
            provider=DataProviderId.FRED,
        ),
        MacroSeriesObservation(
            series_id="DTWEXBGS",
            date=now,
            value=Decimal("104"),
            provider=DataProviderId.FRED,
        ),
    )
    article = NewsArticle(
        article_id="research-news",
        title="Gold finds support as rate-cut expectations rise",
        url="https://example.test/gold",
        source_name="Example",
        published_at=now,
        summary="Policy expectations support gold.",
        provider=DataProviderId.NEWSAPI,
    )
    cot = (
        CotPositioningSnapshot(
            report_date=now,
            market_name="GOLD - COMMODITY EXCHANGE INC.",
            managed_money_long=180000,
            managed_money_short=90000,
            managed_money_net=90000,
        ),
    )
    flow = EtfFlowSnapshot(
        date=now,
        fund="GLD",
        total_ounces=Decimal("25100000"),
        daily_ounce_change=Decimal("100000"),
    )
    market_data = MarketDataSnapshot(
        bars=bars,
        dxy_observations=dxy,
        news_articles=(article,),
        geopolitical_articles=(article,),
        cot_positioning=cot,
        gld_flow=flow,
        collected_at=now,
    )
    technical = TechnicalIntelligenceEngine().analyze(bars)
    fundamental = FundamentalIntelligenceEngine().analyze(dxy, ())
    institutional = InstitutionalIntelligenceEngine().analyze(cot, flow)
    news = NewsIntelligenceEngine().analyze((article,))
    geopolitical = GeopoliticalIntelligenceEngine().analyze((article,))
    decision_config = load_decision_engine_config("config/decision_engine.json")
    regime = MarketRegimeEngine(decision_config.weights).analyze(
        technical,
        fundamental,
        news,
        geopolitical,
    )
    return AnalysisBundle(
        market_data=market_data,
        technical=technical,
        fundamental=fundamental,
        news=news,
        geopolitical=geopolitical,
        institutional=institutional,
        regime=regime,
    )


# --- Escalation routing regression tests -----------------------------------


def _escalation_desk() -> AIResearchDesk:
    return AIResearchDesk(
        config=load_ai_research_config("config/ai_research.json"),
        client=None,
    )


def _stable_escalation_bundle() -> AnalysisBundle:
    """A bundle tuned so that no escalation condition fires by default."""
    bundle = _analysis_bundle()
    technical = bundle.technical.model_copy(update={"score": 65, "evidence": ()})
    fundamental = bundle.fundamental.model_copy(update={"score": 60})
    institutional = bundle.institutional.model_copy(update={"evidence": ()})
    geopolitical = bundle.geopolitical.model_copy(update={"score": 80})
    regime = bundle.regime.model_copy(
        update={
            "regime": MarketRegime.RISK_ON,
            "confidence": ConfidenceScore(
                value=80, reason="Stable risk appetite for escalation tests."
            ),
        }
    )
    return bundle.model_copy(
        update={
            "technical": technical,
            "fundamental": fundamental,
            "institutional": institutional,
            "geopolitical": geopolitical,
            "regime": regime,
        }
    )


def _with_regime(bundle: AnalysisBundle, regime: MarketRegime) -> AnalysisBundle:
    return bundle.model_copy(
        update={"regime": bundle.regime.model_copy(update={"regime": regime})}
    )


def _critical_evidence(evidence_id: str, source: str) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        category="TECHNICAL",
        description="Critical-strength evidence for escalation testing.",
        strength=EvidenceStrength.CRITICAL,
        confidence=100,
        source=source,
    )


def test_stable_regime_does_not_force_deep_reasoning():
    requires, reason = _escalation_desk()._evaluate_escalation(_stable_escalation_bundle())

    assert requires is False
    assert reason is None


@pytest.mark.parametrize(
    "regime",
    [
        MarketRegime.RISK_OFF,
        MarketRegime.HIGH_VOLATILITY,
        MarketRegime.EVENT_DRIVEN,
        MarketRegime.UNKNOWN,
    ],
)
def test_risk_elevated_regimes_still_force_deep_reasoning(regime):
    bundle = _with_regime(_stable_escalation_bundle(), regime)

    requires, reason = _escalation_desk()._evaluate_escalation(bundle)

    assert requires is True
    assert reason == f"Regime transition: {regime.value}"


@pytest.mark.parametrize(
    "regime",
    [MarketRegime.BULL, MarketRegime.BEAR, MarketRegime.RANGE, MarketRegime.LOW_VOLATILITY],
)
def test_trend_and_liquidity_regimes_do_not_auto_escalate(regime):
    bundle = _with_regime(_stable_escalation_bundle(), regime)

    requires, reason = _escalation_desk()._evaluate_escalation(bundle)

    assert requires is False
    assert reason is None


def test_low_regime_confidence_still_escalates():
    bundle = _stable_escalation_bundle()
    bundle = bundle.model_copy(
        update={
            "regime": bundle.regime.model_copy(
                update={
                    "confidence": ConfidenceScore(
                        value=20, reason="Weak regime classification conviction."
                    )
                }
            )
        }
    )

    requires, reason = _escalation_desk()._evaluate_escalation(bundle)

    assert requires is True
    assert reason == "Low decision stability"


def test_geopolitical_shock_still_escalates():
    bundle = _stable_escalation_bundle()
    bundle = bundle.model_copy(
        update={"geopolitical": bundle.geopolitical.model_copy(update={"score": 10})}
    )

    requires, reason = _escalation_desk()._evaluate_escalation(bundle)

    assert requires is True
    assert reason == "Geopolitical shock detected"


def test_engine_disagreement_still_escalates():
    bundle = _stable_escalation_bundle()
    bundle = bundle.model_copy(
        update={
            "technical": bundle.technical.model_copy(update={"score": 95}),
            "fundamental": bundle.fundamental.model_copy(update={"score": 30}),
        }
    )

    requires, reason = _escalation_desk()._evaluate_escalation(bundle)

    assert requires is True
    assert reason == "Strong engine disagreement (Tech vs Fund)"


def test_ambiguous_technical_confidence_still_escalates():
    bundle = _stable_escalation_bundle()
    bundle = bundle.model_copy(
        update={"technical": bundle.technical.model_copy(update={"score": 52})}
    )

    requires, reason = _escalation_desk()._evaluate_escalation(bundle)

    assert requires is True
    assert reason == "Ambiguous technical confidence"


def test_critical_technical_no_data_evidence_escalates_without_attribute_error():
    bundle = _stable_escalation_bundle()
    bundle = bundle.model_copy(
        update={
            "technical": bundle.technical.model_copy(
                update={
                    "evidence": (
                        _critical_evidence("TECH-NODATA-001", "TechnicalIntelligenceEngine"),
                    )
                }
            )
        }
    )

    requires, reason = _escalation_desk()._evaluate_escalation(bundle)

    assert requires is True
    assert reason == "Critical opposing evidence"


def test_critical_extreme_pullback_evidence_escalates():
    bundle = _stable_escalation_bundle()
    bundle = bundle.model_copy(
        update={
            "technical": bundle.technical.model_copy(
                update={
                    "evidence": (
                        _critical_evidence("PULLBACK-RISK-001", "PullbackRiskEngine"),
                    )
                }
            )
        }
    )

    requires, reason = _escalation_desk()._evaluate_escalation(bundle)

    assert requires is True
    assert reason == "Critical opposing evidence"


def test_critical_institutional_evidence_escalates():
    bundle = _stable_escalation_bundle()
    bundle = bundle.model_copy(
        update={
            "institutional": bundle.institutional.model_copy(
                update={
                    "evidence": (
                        _critical_evidence("INST-COT-001", "InstitutionalIntelligenceEngine"),
                    )
                }
            )
        }
    )

    requires, reason = _escalation_desk()._evaluate_escalation(bundle)

    assert requires is True
    assert reason == "Critical opposing evidence"


def test_high_strength_evidence_does_not_trigger_evidence_escalation():
    bundle = _stable_escalation_bundle()
    high_evidence = EvidenceRecord(
        evidence_id="TECH-RSI-001",
        category="TECHNICAL",
        description="Strong but non-critical evidence should not escalate on its own.",
        strength=EvidenceStrength.HIGH,
        confidence=90,
        source="TechnicalIntelligenceEngine",
    )
    bundle = bundle.model_copy(
        update={
            "technical": bundle.technical.model_copy(update={"evidence": (high_evidence,)})
        }
    )

    requires, reason = _escalation_desk()._evaluate_escalation(bundle)

    assert requires is False
    assert reason is None


def test_groq_first_chain_restored_when_no_escalation(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    platform_config = load_platform_config("config/platform.json")
    research_config = load_ai_research_config("config/ai_research.json")
    http = FakeAIHttpClient()
    desk = AIResearchDesk(
        config=research_config,
        client=LLMJsonClient(
            http_client=http,
            groq_config=platform_config.providers[DataProviderId.GROQ],
            gemini_config=platform_config.providers[DataProviderId.GEMINI],
            opencode_config=platform_config.providers[DataProviderId.OPENCODE],
            ollama_config=platform_config.providers[DataProviderId.OLLAMA],
            reasoning_config=platform_config.ai_reasoning,
        ),
    )

    report = desk.analyze(_stable_escalation_bundle())

    assert report.committee_report.provider == "adversarial_committee"
    assert len(http.posts) == 3
    assert all("groq" in post["url"] for post in http.posts)


def test_deep_reasoning_escalation_still_routes_opencode_first(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("OPENCODE_API_KEY", "test-opencode-key")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-ollama-key")
    platform_config = load_platform_config("config/platform.json")
    research_config = load_ai_research_config("config/ai_research.json")
    http = FakeAIHttpClient()
    desk = AIResearchDesk(
        config=research_config,
        client=LLMJsonClient(
            http_client=http,
            groq_config=platform_config.providers[DataProviderId.GROQ],
            gemini_config=platform_config.providers[DataProviderId.GEMINI],
            opencode_config=platform_config.providers[DataProviderId.OPENCODE],
            ollama_config=platform_config.providers[DataProviderId.OLLAMA],
            reasoning_config=platform_config.ai_reasoning,
        ),
    )

    bundle = _with_regime(_stable_escalation_bundle(), MarketRegime.HIGH_VOLATILITY)
    report = desk.analyze(bundle)

    assert report.committee_report.provider == "adversarial_committee"
    assert http.posts
    assert "opencode" in http.posts[0]["url"]
