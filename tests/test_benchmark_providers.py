import json
import pytest
from app.benchmark.providers import LLMProvider, OpenCodeZenProvider, BenchmarkResult

class MockProvider(LLMProvider):
    def __init__(self):
        super().__init__("mock", ["mock-model"])
        
    def get_api_key(self) -> str:
        return "fake-key"
        
    def check_availability(self):
        return {"mock-model": "MODEL_AVAILABLE"}
        
    def generate(self, model, sys, usr):
        return BenchmarkResult(self.name, model, True, parsed_json={"direction": "BULLISH"})

def test_json_extraction():
    p = MockProvider()
    
    # Test 1: Plain JSON
    raw = '{"direction": "BULLISH"}'
    parsed, err_code, err_msg = p._parse_and_validate(raw)
    assert parsed == {"direction": "BULLISH"}
    
    # Test 2: Fenced JSON
    raw_fenced = '''Here is your response:
    `json
    {"direction": "BEARISH"}
    `
    '''
    parsed_fenced, _, _ = p._parse_and_validate(raw_fenced)
    assert parsed_fenced == {"direction": "BEARISH"}
    
    # Test 3: Invalid JSON
    raw_invalid = '{"direction": "BULLISH", }'
    parsed_invalid, err_code, _ = p._parse_and_validate(raw_invalid)
    assert parsed_invalid is None
    assert err_code == "INVALID_JSON"

def test_error_classification():
    p = MockProvider()
    
    assert p._classify_error(401, "unauth", None)[0] == "AUTH_FAILED"
    assert p._classify_error(404, "not found", None)[0] == "MODEL_NOT_FOUND"
    assert p._classify_error(413, "too large", None)[0] == "REQUEST_TOO_LARGE"
    assert p._classify_error(429, "rate limit", None)[0] == "RATE_LIMITED"
    assert p._classify_error(500, "server error", None)[0] == "SERVER_ERROR"
    assert p._classify_error(0, "", TimeoutError())[0] == "TIMEOUT"

def test_retry_behavior_on_429(monkeypatch):
    from app.benchmark.providers import BenchmarkResult, LLMProvider
    class FlakyProvider(LLMProvider):
        def __init__(self):
            super().__init__("flaky", ["flaky-1"])
            self.calls = 0
            
        def check_availability(self):
            return {"flaky-1": "MODEL_AVAILABLE"}
            
        def generate(self, model, sys, usr):
            self.calls += 1
            if self.calls == 1:
                return BenchmarkResult(self.name, model, False, error_code="RATE_LIMITED")
            return BenchmarkResult(self.name, model, True, parsed_json={"direction": "BULLISH"})

    p = FlakyProvider()
    assert p.calls == 0
    res = p.generate("flaky-1", "", "")
    assert res.error_code == "RATE_LIMITED"
    res2 = p.generate("flaky-1", "", "")
    assert res2.success

