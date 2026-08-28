import json
from datetime import UTC, datetime

from app.ai.agents.news_analyst import GroqNewsAnalystAgent
from app.application.engines.news_engine import NewsIntelligenceEngine
from app.application.http import HttpResponse
from app.application.platform_config import LLMProviderConfig
from app.domain.ai import (
    AIContext,
    AIGoldImpactDirection,
    AINewsImpactAssessment,
)
from app.domain.common import ContractStatus
from app.domain.intelligence import DirectionalBias
from app.domain.market_data import DataProviderId, NewsArticle
from app.infrastructure.config_loader import load_platform_config


class FakeAIHttpClient:
    def __init__(self, responses: tuple[HttpResponse, ...]) -> None:
        self._responses = list(responses)
        self.posts = []

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        raise AssertionError("AI agent should not issue GET requests")

    def post(self, url, body, params=None, headers=None, timeout_seconds=10.0):
        self.posts.append(
            {
                "url": url,
                "body": json.loads(body),
                "params": params or {},
                "headers": headers or {},
            }
        )
        return self._responses.pop(0)


def test_groq_news_agent_returns_structured_bullish_gold_assessment(monkeypatch):
    config = load_platform_config("config/platform.json")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = FakeAIHttpClient(
        (
            HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "severity": 68,
                                            "gold_impact_direction": "BULLISH",
                                            "gold_impact_magnitude": 72,
                                            "reliability": 81,
                                            "reasoning": (
                                                "Lower expected real rates improve the "
                                                "relative appeal of non-yielding gold."
                                            ),
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ),
            ),
        )
    )
    agent = GroqNewsAnalystAgent(
        http_client=http,
        groq_config=config.providers[DataProviderId.GROQ],
            gemini_config=config.providers[DataProviderId.GEMINI],
            opencode_config=config.providers[DataProviderId.OPENCODE],
            ollama_config=config.providers[DataProviderId.OLLAMA],
            reasoning_config=config.ai_reasoning,
    )

    assessment, raw_json, provider = agent.analyze_impact(
        AIContext(
            context_id="headline-fed-cut",
            objective="Assess headline impact for gold.",
            facts={"headline": "Fed signals rate cut amid inflation concerns"},
        )
    )

    assert provider == "groq"
    assert raw_json
    assert assessment.gold_impact_direction == AIGoldImpactDirection.BULLISH
    assert assessment.gold_impact_magnitude == 72
    assert "real rates" in assessment.reasoning
    assert http.posts[0]["body"]["model"] == "openai/gpt-oss-120b"


def test_news_agent_uses_groq_when_gemini_fails(monkeypatch):
    # This test builds its own explicit gemini-first, then-groq reasoning_config rather
    # than relying on platform.json's default order (which is groq-first, gemini-second)
    # specifically to exercise cross-provider fallback: a single config-driven chain is
    # shared by both the committee and this lighter per-article agent, instead of two
    # independently hardcoded orders. Scoped to one Gemini model so this test covers
    # cross-provider fallback specifically, independent of how many fallback models
    # platform.json happens to list for Gemini itself (that's covered separately).
    config = load_platform_config("config/platform.json")
    groq_entry = next(entry for entry in config.ai_reasoning.providers if entry.provider == "groq")
    reasoning_config = config.ai_reasoning.model_copy(
        update={
            "providers": (
                LLMProviderConfig(provider="gemini", models=("gemini-3.5-flash",)),
                groq_entry,
            )
        }
    )
    groq_model = groq_entry.models[0]
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = FakeAIHttpClient(
        (
            HttpResponse(status_code=503, body="gemini unavailable"),
            HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "severity": 55,
                                            "gold_impact_direction": "BULLISH",
                                            "gold_impact_magnitude": 60,
                                            "reliability": 70,
                                            "reasoning": (
                                                "Fallback model sees policy easing "
                                                "as supportive for gold."
                                            ),
                                        }
                                    )
                                }
                            }
                        ],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                    }
                ),
            ),
        )
    )
    agent = GroqNewsAnalystAgent(
        http_client=http,
        groq_config=config.providers[DataProviderId.GROQ],
            gemini_config=config.providers[DataProviderId.GEMINI],
            opencode_config=config.providers[DataProviderId.OPENCODE],
            ollama_config=config.providers[DataProviderId.OLLAMA],
            reasoning_config=reasoning_config,
    )

    assessment, _raw_json, provider = agent.analyze_impact(
        AIContext(
            context_id="headline-fed-cut",
            objective="Assess headline impact for gold.",
            facts={"headline": "Fed signals rate cut amid inflation concerns"},
        )
    )

    assert provider == "groq"
    assert assessment.gold_impact_direction == AIGoldImpactDirection.BULLISH
    assert "responseMimeType" not in http.posts[0]["body"]
    assert http.posts[1]["body"]["model"] == groq_model


def test_news_engine_degrades_to_keyword_fallback_when_api_keys_are_missing(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config = load_platform_config("config/platform.json")
    agent = GroqNewsAnalystAgent(
        http_client=FakeAIHttpClient(()),
        groq_config=config.providers[DataProviderId.GROQ],
            gemini_config=config.providers[DataProviderId.GEMINI],
            opencode_config=config.providers[DataProviderId.OPENCODE],
            ollama_config=config.providers[DataProviderId.OLLAMA],
            reasoning_config=config.ai_reasoning,
    )
    engine = NewsIntelligenceEngine(ai_agent=agent, ai_reasoning_enabled=True)

    result = engine.analyze(
        (
            NewsArticle(
                article_id="fed-cut",
                title="Fed signals rate cut amid inflation concerns",
                url="https://example.com/fed-cut",
                source_name="Example",
                published_at=datetime.now(UTC),
                summary="Policy makers turn dovish while inflation risk lingers.",
                provider=DataProviderId.GDELT,
            ),
        )
    )

    assert result.status == ContractStatus.SUCCESS
    assert result.bias == DirectionalBias.BULLISH
    assert result.confidence.value <= 35
    assert "AI fallback reason" in result.evidence[0].description
    assert result.risks


def _fresh_article() -> NewsArticle:
    return NewsArticle(
        article_id="gold-fed",
        title="Fed signals rate cut amid inflation concerns",
        url="https://example.com/gold-fed",
        source_name="Example",
        published_at=datetime.now(UTC),
        summary="Policy makers turn dovish while inflation risk lingers.",
        provider=DataProviderId.GDELT,
    )


def test_news_engine_truncates_long_ai_reasoning():
    class LongReasoningAgent:
        def analyze_impact(self, context):
            return (
                AINewsImpactAssessment(
                    severity=68,
                    gold_impact_direction=AIGoldImpactDirection.BULLISH,
                    gold_impact_magnitude=72,
                    reliability=81,
                    reasoning="rising real yields and safe haven demand keep gold supported " * 10,
                ),
                "{}",
                "stub",
            )

    engine = NewsIntelligenceEngine(ai_agent=LongReasoningAgent(), ai_reasoning_enabled=True)

    result = engine.analyze((_fresh_article(),))

    assert result.status == ContractStatus.SUCCESS
    ai_evidence = [item for item in result.evidence if item.evidence_id == "NEWS-AI-001"]
    assert len(ai_evidence) == 1
    assert len(ai_evidence[0].description) <= 500
    assert ai_evidence[0].description.startswith("BULLISH gold impact (72/100): ")
    assert not any(item.evidence_id == "NEWS-FALLBACK-001" for item in result.evidence)
