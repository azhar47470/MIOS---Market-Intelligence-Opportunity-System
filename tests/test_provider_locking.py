import os
import json
import pytest

from app.ai.agents.llm_client import LLMJsonClient
from app.ai.committee import AdversarialCommittee
from app.domain.ai import AIContext
from app.infrastructure.config_loader import load_ai_research_config, load_platform_config
from app.domain.market_data import DataProviderId
from app.application.http import HttpResponse

os.environ["GROQ_API_KEY"] = "mock"
os.environ["OPENCODE_API_KEY"] = "mock"
os.environ["OLLAMA_API_KEY"] = "mock"
os.environ["GEMINI_API_KEY"] = "mock"

class MockHttpClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def post(self, url, body=None, headers=None, timeout_seconds=None, **kwargs):
        self.calls.append(url)
        if hasattr(self, "callback"):
            return self.callback(url)
        return self.responses.pop(0)

@pytest.fixture
def config():
    return load_ai_research_config("config/ai_research.json")

@pytest.fixture
def platform_config():
    return load_platform_config("config/platform.json")

def test_committee_provider_locking(config, platform_config):
    def callback(url):
        return HttpResponse(status_code=200, body=json.dumps({"choices": [{"message": {"content": '{"direction": "LONG", "confidence": 0.9, "reasoning": "R", "key_risk": "K", "time_horizon": "T"}'}}]}))
    http_client = MockHttpClient([])
    http_client.callback = callback
    
    client = LLMJsonClient(
        http_client=http_client,
        groq_config=platform_config.providers[DataProviderId.GROQ],
        gemini_config=platform_config.providers[DataProviderId.GEMINI],
        opencode_config=platform_config.providers[DataProviderId.OPENCODE],
        ollama_config=platform_config.providers[DataProviderId.OLLAMA],
        reasoning_config=platform_config.ai_reasoning,
    )
    committee = AdversarialCommittee(client=client, config=config)
    report = committee.deliberate(AIContext(context_id="ctx", objective="test", facts={}), tuple())
    
    assert report.provider == "adversarial_committee"
    assert "groq" in http_client.calls[0]
    assert "groq" in http_client.calls[1]
    assert "groq" in http_client.calls[2]

def test_laguna_schema_failure_triggers_switch(config, platform_config):
    def callback(url):
        if "opencode" in url:
            return HttpResponse(status_code=200, body=json.dumps({"choices": [{"message": {"content": 'Invalid Schema'}}]}))
        return HttpResponse(status_code=200, body=json.dumps({"choices": [{"message": {"content": '{"direction": "LONG", "confidence": 0.9, "reasoning": "R", "key_risk": "K", "time_horizon": "T"}'}}]}))
    http_client = MockHttpClient([])
    http_client.callback = callback

    client = LLMJsonClient(
        http_client=http_client,
        groq_config=platform_config.providers[DataProviderId.GROQ],
        gemini_config=platform_config.providers[DataProviderId.GEMINI],
        opencode_config=platform_config.providers[DataProviderId.OPENCODE],
        ollama_config=platform_config.providers[DataProviderId.OLLAMA],
        reasoning_config=platform_config.ai_reasoning,
    )
    committee = AdversarialCommittee(client=client, config=config)
    report = committee.deliberate(AIContext(context_id="ctx", objective="test", facts={}), tuple(), requires_deep_reasoning=True)
    
    assert "opencode" in http_client.calls[0]
    assert "groq" in http_client.calls[1]
    assert "groq" in http_client.calls[2]
    assert "groq" in http_client.calls[3]

def test_gemini_fallback(config, platform_config):
    def callback(url):
        if "opencode" in url or "groq" in url or "ollama" in url:
            return HttpResponse(status_code=500, body="{}")
        return HttpResponse(status_code=200, body=json.dumps({"candidates": [{"content": {"parts": [{"text": '{"direction": "LONG", "confidence": 0.9, "reasoning": "R", "key_risk": "K", "time_horizon": "T"}'}]}}]}))
    http_client = MockHttpClient([])
    http_client.callback = callback

    client = LLMJsonClient(
        http_client=http_client,
        groq_config=platform_config.providers[DataProviderId.GROQ],
        gemini_config=platform_config.providers[DataProviderId.GEMINI],
        opencode_config=platform_config.providers[DataProviderId.OPENCODE],
        ollama_config=platform_config.providers[DataProviderId.OLLAMA],
        reasoning_config=platform_config.ai_reasoning,
    )
    committee = AdversarialCommittee(client=client, config=config)
    report = committee.deliberate(AIContext(context_id="ctx", objective="test", facts={}), tuple(), requires_deep_reasoning=True)
    
    assert "opencode" in http_client.calls[0]
    assert "groq" in http_client.calls[1]
    assert "ollama" in http_client.calls[2]
    assert "generativelanguage" in http_client.calls[3]
    assert "generativelanguage" in http_client.calls[4]
    assert "generativelanguage" in http_client.calls[5]

def test_ollama_malformed_response_falls_through(config, platform_config):
    def callback(url):
        if "opencode" in url or "groq" in url:
            return HttpResponse(status_code=500, body="{}")
        if "ollama" in url:
            return HttpResponse(status_code=200, body=json.dumps({"strange_key": "strange_value"}))
        return HttpResponse(status_code=200, body=json.dumps({"candidates": [{"content": {"parts": [{"text": '{"direction": "LONG", "confidence": 0.9, "reasoning": "R", "key_risk": "K", "time_horizon": "T"}'}]}}]}))
    http_client = MockHttpClient([])
    http_client.callback = callback

    client = LLMJsonClient(
        http_client=http_client,
        groq_config=platform_config.providers[DataProviderId.GROQ],
        gemini_config=platform_config.providers[DataProviderId.GEMINI],
        opencode_config=platform_config.providers[DataProviderId.OPENCODE],
        ollama_config=platform_config.providers[DataProviderId.OLLAMA],
        reasoning_config=platform_config.ai_reasoning,
    )
    committee = AdversarialCommittee(client=client, config=config)
    report = committee.deliberate(AIContext(context_id="ctx", objective="test", facts={}), tuple(), requires_deep_reasoning=False)
    
    assert "groq" in http_client.calls[0]
    assert "opencode" in http_client.calls[1]
    assert "ollama" in http_client.calls[2]
    assert "generativelanguage" in http_client.calls[3]
    assert "generativelanguage" in http_client.calls[4]
    assert "generativelanguage" in http_client.calls[5]

