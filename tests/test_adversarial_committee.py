import json

from app.ai.agents.llm_client import AIProviderError, LLMJsonClient
from app.ai.committee import (
    AdversarialCommittee,
    CommitteeDirection,
    MemberVote,
)
from app.application.ai_research_config import AIResearchConfig
from app.domain.ai import AIContext, AnalystReport
from app.domain.enums import Recommendation
from app.domain.market_data import DataProviderId
from app.domain.ai import AgentRole
from app.application.http import HttpResponse
from app.infrastructure.config_loader import (
    load_ai_research_config,
    load_platform_config,
)

_ctx = AIContext(context_id="ctx-1", objective="Objective", facts={"technical": {"x": 1}})


def _report(role: AgentRole, recommendation: Recommendation, confidence: int) -> AnalystReport:
    return AnalystReport(
        report_id=f"r-{role.value}",
        role=role,
        context_id="ctx-1",
        provider="deterministic_fallback",
        summary="Desk report.",
        confidence=confidence,
        recommendation=recommendation,
    )


def _config() -> AIResearchConfig:
    return load_ai_research_config("config/ai_research.json")


class StubMember:
    def __init__(self, name, weight, direction, confidence, provider="gemini") -> None:
        self._name = name
        self._weight = weight
        self._direction = direction
        self._confidence = confidence
        self._provider = provider

    @property
    def name(self) -> str:
        return self._name

    @property
    def weight(self) -> float:
        return self._weight

    def vote(self, context, reports, requires_deep_reasoning=False) -> MemberVote:
        return MemberVote(
            member_name=self._name,
            direction=self._direction,
            confidence=self._confidence,
            reasoning=f"{self._name} reasoning.",
            weight=self._weight,
            provider=self._provider,
        )


def _committee(members) -> AdversarialCommittee:
    return AdversarialCommittee(client=None, config=_config(), members=tuple(members))


def test_consensus_weights_votes_by_confidence_times_weight():
    committee = _committee(
        [
            StubMember("Bull A", 0.30, CommitteeDirection.BUY, 1.0),
            StubMember("Bull B", 0.25, CommitteeDirection.BUY, 1.0),
            StubMember("Bear", 0.20, CommitteeDirection.SELL, 1.0),
            StubMember("Waiter", 0.25, CommitteeDirection.WAIT, 1.0),
        ]
    )

    report = committee.deliberate(_ctx, ())

    assert report.final_recommendation is Recommendation.BUY
    assert report.confidence == 55
    assert report.confidence_adjustment == 4
    assert "moderate" in report.summary.lower()
    assert report.provider == "adversarial_committee"


def test_strong_consensus_maps_to_strong_buy_with_higher_adjustment():
    committee = _committee(
        [
            StubMember("Bull A", 0.30, CommitteeDirection.BUY, 1.0),
            StubMember("Bull B", 0.25, CommitteeDirection.BUY, 1.0),
            StubMember("Bull C", 0.20, CommitteeDirection.BUY, 1.0),
            StubMember("Waiter", 0.25, CommitteeDirection.WAIT, 1.0),
        ]
    )

    report = committee.deliberate(_ctx, ())

    assert report.final_recommendation is Recommendation.STRONG_BUY
    assert report.confidence == 75
    assert report.confidence_adjustment == 8
    assert "strong" in report.summary.lower()
    # Strong consensus requires no further confirmation.
    assert report.required_confirmations == ()


def test_fragmented_consensus_votes_wait_with_negative_adjustment():
    committee = _committee(
        [
            StubMember("Bull", 0.30, CommitteeDirection.BUY, 0.34),
            StubMember("Bear", 0.25, CommitteeDirection.SELL, 0.34),
            StubMember("Waiter A", 0.20, CommitteeDirection.WAIT, 0.34),
            StubMember("Waiter B", 0.25, CommitteeDirection.WAIT, 0.34),
        ]
    )

    report = committee.deliberate(_ctx, ())

    assert report.final_recommendation is Recommendation.WAIT
    assert "fragmented" in report.summary.lower()
    assert report.confidence_adjustment == -6
    assert report.required_confirmations
    # Both directions are present, so opposing evidence is surfaced.
    assert report.conflicting_evidence
    assert report.why_not_buy != report.why_not_sell


def test_no_ai_votes_reports_deterministic_fallback_committee():
    committee = _committee(
        [
            StubMember("Anchor", 0.25, CommitteeDirection.WAIT, 0.4, provider="deterministic"),
            StubMember("Failed A", 0.30, CommitteeDirection.WAIT, 0.4, provider="fallback"),
            StubMember("Failed B", 0.25, CommitteeDirection.WAIT, 0.4, provider="fallback"),
            StubMember("Failed C", 0.20, CommitteeDirection.WAIT, 0.4, provider="fallback"),
        ]
    )

    report = committee.deliberate(_ctx, ())

    assert report.provider == "deterministic_fallback"
    assert report.fallback_reason is not None
    assert report.confidence_adjustment == _config().committee_fallback_confidence_adjustment
    assert len(report.missing_evidence) == 3
    assert report.required_confirmations


class RaisingLLMClient(LLMJsonClient):
    def complete(
        self,
        system_prompt,
        user_prompt,
        *,
        is_valid=None,
        requires_deep_reasoning=False,
        preferred_provider=None,
        force_provider=None,
        temperature=None,
    ):
        raise AIProviderError("all providers failed")


def test_all_llm_members_failing_keeps_quorum_via_desk_votes():
    platform_config = load_platform_config("config/platform.json")
    client = RaisingLLMClient(
        http_client=None,
        groq_config=platform_config.providers[DataProviderId.GROQ],
        gemini_config=platform_config.providers[DataProviderId.GEMINI],
        opencode_config=platform_config.providers[DataProviderId.OPENCODE],
        ollama_config=platform_config.providers[DataProviderId.OLLAMA],
        reasoning_config=platform_config.ai_reasoning,
    )
    committee = AdversarialCommittee(client=client, config=_config())
    reports = (
        _report(AgentRole.TECHNICAL_ANALYST, Recommendation.BUY, 80),
        _report(AgentRole.RISK_ANALYST, Recommendation.TAKE_PROFIT, 70),
    )

    report = committee.deliberate(_ctx, reports)

    assert report.provider == "deterministic_fallback"
    # Four votes still happened: the anchor plus three desk-evidence fallbacks.
    assert "across 4 committee members" in report.summary
    assert len(report.missing_evidence) == 3
    assert report.confidence_adjustment == _config().committee_fallback_confidence_adjustment


class RecordingHTTP:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        raise AssertionError("committee should not GET")

    def post(self, url, body, params=None, headers=None, timeout_seconds=10.0):
        payload = json.loads(body)
        self.posts.append({"url": url, "payload": payload})
        vote = json.dumps(
            {
                "direction": "LONG",
                "confidence": 0.62,
                "reasoning": "Momentum and macro alignment favor gold.",
                "key_risk": "Stronger dollar.",
                "time_horizon": "1-4 weeks",
            }
        )
        if "groq" in url:
            return HttpResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "choices": [{"message": {"content": vote}}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                    }
                ),
            )
        return HttpResponse(
            status_code=200,
            body=json.dumps(
                {
                    "candidates": [{"content": {"parts": [{"text": vote}]}}],
                    "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
                }
            ),
        )


def test_ai_members_are_pinned_to_provider_and_temperature(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    platform_config = load_platform_config("config/platform.json")
    http = RecordingHTTP()
    client = LLMJsonClient(
        http_client=http,
        groq_config=platform_config.providers[DataProviderId.GROQ],
        gemini_config=platform_config.providers[DataProviderId.GEMINI],
        opencode_config=platform_config.providers[DataProviderId.OPENCODE],
        ollama_config=platform_config.providers[DataProviderId.OLLAMA],
        reasoning_config=platform_config.ai_reasoning,
    )
    committee = AdversarialCommittee(client=client, config=_config())

    report = committee.deliberate(_ctx, ())

    assert report.provider == "adversarial_committee"
    gemini_posts = [p for p in http.posts if "generativelanguage" in p["url"]]
    groq_posts = [p for p in http.posts if "groq" in p["url"]]
    assert len(gemini_posts) == 0
    assert len(groq_posts) == 3
    assert {p["payload"]["temperature"] for p in groq_posts} == {0.4, 0.5, 0.6}
    
    assert report.usage is not None
    assert report.usage.prompt_tokens == 15
    assert report.final_recommendation is Recommendation.BUY
    assert report.confidence == 46


class GarbageHTTP:
    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        raise AssertionError("committee should not GET")

    def post(self, url, body, params=None, headers=None, timeout_seconds=10.0):
        return HttpResponse(
            status_code=200,
            body=json.dumps({"choices": [{"message": {"content": "not json at all"}}]}),
        )


def test_schema_invalid_member_votes_fall_back_to_desk_evidence(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    platform_config = load_platform_config("config/platform.json")
    http = GarbageHTTP()
    client = LLMJsonClient(
        http_client=http,
        groq_config=platform_config.providers[DataProviderId.GROQ],
        gemini_config=platform_config.providers[DataProviderId.GEMINI],
        opencode_config=platform_config.providers[DataProviderId.OPENCODE],
        ollama_config=platform_config.providers[DataProviderId.OLLAMA],
        reasoning_config=platform_config.ai_reasoning,
    )
    committee = AdversarialCommittee(client=client, config=_config())
    reports = (
        _report(AgentRole.TECHNICAL_ANALYST, Recommendation.BUY, 80),
        _report(AgentRole.NEWS_ANALYST, Recommendation.BUY, 60),
        _report(AgentRole.RISK_ANALYST, Recommendation.WAIT, 50),
    )

    report = committee.deliberate(_ctx, reports)

    # Every AI member produced garbage votes, so the committee is a full fallback, but the
    # desk evidence still drives a coherent vote and the report is valid.
    assert report.provider == "deterministic_fallback"
    assert len(report.missing_evidence) == 3
    assert report.final_recommendation in {
        Recommendation.BUY,
        Recommendation.STRONG_BUY,
        Recommendation.WAIT,
    }
    assert len(report.required_confirmations) == 1
