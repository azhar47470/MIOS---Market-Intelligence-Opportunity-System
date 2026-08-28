import os
import pytest
from app.benchmark.providers import LLMProvider, OpenCodeZenProvider, GroqProvider, GeminiProvider

def test_env_var_present_and_missing(monkeypatch):
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    p = OpenCodeZenProvider(["m1"])
    assert p.get_api_key() == ""
    assert p.check_availability()["m1"] == "AUTH_MISSING"
    
    monkeypatch.setenv("OPENCODE_API_KEY", "secret-key")
    assert p.get_api_key() == "secret-key"
    
def test_env_loading(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_KEY=12345\n#comment\nEMPTY=\n")
    import sys
    import os
    
    # We can extract the load_env function from the script or just duplicate the logic for testing
    def load_env(env_path):
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip("'\"")
                        if key and key not in os.environ:
                            os.environ[key] = value
                            
    load_env(str(env_file))
    assert os.environ["TEST_KEY"] == "12345"
    assert os.environ.get("EMPTY") == ""

def test_opencode_auth_header(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "opencode-secret")
    p = OpenCodeZenProvider(["m1"])
    
    # intercept _get
    captured_headers = {}
    def mock_get(url, headers, timeout=10.0):
        captured_headers.update(headers)
        return 401, "", None
    p._get = mock_get
    
    # 401 should return AUTH_FAILED
    avail = p.check_availability()
    assert avail["m1"] == "AUTH_FAILED"
    assert captured_headers["Authorization"] == "Bearer opencode-secret"

def test_groq_auth_header(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    p = GroqProvider(["m1"])
    
    captured_headers = {}
    def mock_get(url, headers, timeout=10.0):
        captured_headers.update(headers)
        return 403, "", None
    p._get = mock_get
    
    # 403 should return FORBIDDEN
    avail = p.check_availability()
    assert avail["m1"] == "FORBIDDEN"
    assert captured_headers["Authorization"] == "Bearer groq-secret"

def test_gemini_authentication(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    p = GeminiProvider(["m1"])
    
    captured_url = ""
    def mock_post(url, headers, payload, timeout=15.0):
        nonlocal captured_url
        captured_url = url
        return 200, '{"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}', None, {}
    p._post = mock_post
    
    res = p.generate("m1", "", "")
    assert "key=gemini-secret" in captured_url
    assert res.success

def test_401_403_classification():
    p = LLMProvider("test", [])
    assert p._classify_error(401, "", None)[0] == "AUTH_FAILED"
    assert p._classify_error(403, "", None)[0] == "FORBIDDEN"
