import jsonimport osimport time

import pytest

from app.ai.agents import llm_client as llm_client_modulefrom app.ai.agents.llm_client import AIProviderError, LLMJsonClient, _acquire_groq_lock
from app.application.http import HttpResponse
from app.application.platform_config import AIReasoningConfig, LLMProviderConfig
from app.domain.market_data import DataProviderId
from app.infrastructure.config_loader import load_platform_config


class ScriptedHttpClient:
    """Returns one scripted response per URL substring; records every POST's url and body.

    Gemini's endpoint path embeds the model name (``/models/{model}:generateContent``), so a
    fragment like ``"gemini-2.5-flash"`` targets one specific model in the router's try-list
    without needing a sequential response queue.
    """

    def __init__(self, responses_by_url_fragment: dict[str, HttpResponse]) -> None:
        self._responses = responses_by_url_fragment
        self.posts: list[str] = []
        self.bodies: list[str] = []

    def get(self, url, params=None, headers=None, timeout_seconds=10.0):
        raise AssertionError("LLM client should not issue GET requests")

    def post(self, url, body, params=None, headers=None, timeout_seconds=10.0):
        self.posts.append(url)
        self.bodies.append(body)
        for fragment, response in self._responses.items():
            if fragment in url:
                return response
        raise AssertionError(f"Unexpected POST to {url}")


def _reasoning_config(
    *,
    gemini_models: tuple[str, ...] = (),
    groq_models: tuple[str, ...] = (),
    gemini_enabled: bool = True,
    groq_enabled: bool = True,
) -> AIReasoningConfig:
    providers = []
    if gemini_models:
        providers.append(
            LLMProviderConfig(provider="gemini", enabled=gemini_enabled, models=gemini_models)
        )
    if groq_models:
        providers.append(
            LLMProviderConfig(provider="groq", enabled=groq_enabled, models=groq_models)
        )
    return AIReasoningConfig(providers=tuple(providers))


def _client(http, reasoning_config: AIReasoningConfig | None = None) -> LLMJsonClient:
    platform_config = load_platform_config("config/platform.json")
    return LLMJsonClient(
        http_client=http,
        groq_config=platform_config.providers[DataProviderId.GROQ],
        gemini_config=platform_config.providers[DataProviderId.GEMINI],
        opencode_config=platform_config.providers[DataProviderId.OPENCODE],
        ollama_config=platform_config.providers[DataProviderId.OLLAMA],
        reasoning_config=reasoning_config or platform_config.ai_reasoning,
    )


def _chat_completion_response(marker: str) -> HttpResponse:
    return HttpResponse(
        status_code=200,
        body=json.dumps(
            {
                "choices": [{"message": {"content": json.dumps({"marker": marker})}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            }
        ),
    )


def _groq_lock_client(tmp_path, monkeypatch, http, reasoning_config=None) -> LLMJsonClient:    """Groq-enabled client whose serialization lock lives inside tmp_path, never %TEMP%."""    monkeypatch.setattr(llm_client_module, "_GROQ_LOCK_FILE", str(tmp_path / "mios_groq.lock"))    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")    return _client(        http,        reasoning_config or _reasoning_config(groq_models=("test-model",)),    )def _shrink_lock_waits(monkeypatch) -> None:    """Shrink the real 45s/120s bounds so lock tests stay sub-second."""    monkeypatch.setattr(llm_client_module, "_GROQ_LOCK_MAX_WAIT_SECONDS", 0.2)    monkeypatch.setattr(llm_client_module, "_GROQ_LOCK_STALE_AFTER_SECONDS", 300.0)    monkeypatch.setattr(llm_client_module, "_GROQ_LOCK_POLL_SECONDS", 0.01)class TestGroqSerializationLock:    """Bounded-wait / stale-lock hardening for the Groq rate-limit serialization lock."""    def test_healthy_lock_acquires_immediately_when_free(self, tmp_path):        # A: healthy behavior - free lock acquires on the first try, no waiting.        lock_path = str(tmp_path / "mios_groq.lock")        assert _acquire_groq_lock(lock_path) is not None        assert os.path.exists(lock_path)    def test_healthy_lock_waits_for_release_then_acquires(self, tmp_path, monkeypatch):        # A: healthy behavior - a held lock is waited out and acquired once released.        lock_path = str(tmp_path / "mios_groq.lock")        open(lock_path, "w").close()        start = time.perf_counter()        def release_after_delay(seconds: float) -> float:            if time.perf_counter() - start >= 0.15 and os.path.exists(lock_path):                os.remove(lock_path)            return 0.01        monkeypatch.setattr(time, "sleep", release_after_delay)        wait_ms = _acquire_groq_lock(            lock_path,            max_wait_seconds=5.0,            stale_after_seconds=3600.0,            poll_seconds=0.01,        )        assert wait_ms is not None        assert wait_ms >= 100    def test_stale_lock_is_reclaimed_after_bounded_wait(self, tmp_path):        # B: a lock older than the staleness window is reclaimed and acquired.        lock_path = str(tmp_path / "mios_groq.lock")        open(lock_path, "w").close()        old = time.time() - 500.0        os.utime(lock_path, (old, old))        wait_ms = _acquire_groq_lock(            lock_path,            max_wait_seconds=0.2,            stale_after_seconds=300.0,            poll_seconds=0.01,        )        assert wait_ms is not None        assert os.path.exists(lock_path)    def test_fresh_lock_is_not_reclaimed_prematurely(self, tmp_path):        # C: an active-looking lock (fresh mtime) must never be reclaimed; bail out.        lock_path = str(tmp_path / "mios_groq.lock")        open(lock_path, "w").close()        result = _acquire_groq_lock(            lock_path,            max_wait_seconds=0.15,            stale_after_seconds=300.0,            poll_seconds=0.01,        )        assert result is None        assert os.path.exists(lock_path)  # untouched, still belongs to the holder    def test_max_wait_exits_instead_of_hanging_forever(self, tmp_path):        # D: the wait is finite even when the lock is held and never looks stale.        lock_path = str(tmp_path / "mios_groq.lock")        open(lock_path, "w").close()        start = time.perf_counter()        result = _acquire_groq_lock(            lock_path,            max_wait_seconds=0.3,            stale_after_seconds=3600.0,            poll_seconds=0.01,        )        elapsed = time.perf_counter() - start        assert result is None        assert elapsed < 5.0  # generous upper bound; real bound is 0.3s    def test_lock_removed_after_successful_call(self, tmp_path, monkeypatch):        # E: cleanup after success - the lock file is gone after a normal Groq call.        client = _groq_lock_client(            tmp_path, monkeypatch,            ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq")}),        )        completion = client.complete("system", "user")        assert completion.provider == "groq"        assert not os.path.exists(str(tmp_path / "mios_groq.lock"))    def test_lock_removed_after_provider_failure(self, tmp_path, monkeypatch):        # F: cleanup after failure - even a permanent Groq error releases the lock.        client = _groq_lock_client(            tmp_path, monkeypatch,            ScriptedHttpClient({"api.groq.com": HttpResponse(status_code=401, body="unauthorized")}),        )        with pytest.raises(AIProviderError):            client.complete("system", "user")        assert not os.path.exists(str(tmp_path / "mios_groq.lock"))    def test_groq_429_backoff_behavior_unchanged(self, tmp_path, monkeypatch):        # G: 429 handling (bounded backoff then retry) is untouched by the lock change.        class SequentialHttpClient:            def __init__(self, responses):                self._responses = list(responses)                self.count = 0            def get(self, url, params=None, headers=None, timeout_seconds=10.0):                raise AssertionError("LLM client should not issue GET requests")            def post(self, url, body, params=None, headers=None, timeout_seconds=10.0):                self.count += 1                return self._responses.pop(0)        http = SequentialHttpClient([            HttpResponse(status_code=429, body="rate limited, try again in 0.1s"),            _chat_completion_response("groq-after-429"),        ])        client = _groq_lock_client(tmp_path, monkeypatch, http)        completion = client.complete("system", "user")        assert completion.provider == "groq"        assert http.count == 2        assert completion.usage.retry_count == 1        assert not os.path.exists(str(tmp_path / "mios_groq.lock"))    def test_stale_lock_reclaim_via_full_call_path(self, tmp_path, monkeypatch):        # B (integration): a stale lock from a crashed run does not block the next call.        _shrink_lock_waits(monkeypatch)        lock_path = str(tmp_path / "mios_groq.lock")        open(lock_path, "w").close()        old = time.time() - 500.0        os.utime(lock_path, (old, old))        client = _groq_lock_client(            tmp_path, monkeypatch,            ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq-reclaimed")}),        )        monkeypatch.setattr(llm_client_module, "_GROQ_LOCK_FILE", lock_path)        completion = client.complete("system", "user")        assert completion.provider == "groq"        assert not os.path.exists(lock_path)    def test_unrecoverable_lock_timeout_falls_back_to_next_provider(self, tmp_path, monkeypatch):        # D (integration): a fresh, non-stale lock yields a controlled 'lock_timeout'        # status and the existing provider fallback chain continues to Gemini.        _shrink_lock_waits(monkeypatch)        monkeypatch.setattr(llm_client_module, "_GROQ_LOCK_STALE_AFTER_SECONDS", 3600.0)        lock_path = str(tmp_path / "mios_groq.lock")        open(lock_path, "w").close()  # held by a plausibly active process        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")        reasoning_config = AIReasoningConfig(providers=(            LLMProviderConfig(provider="groq", enabled=True, models=("test-model",)),            LLMProviderConfig(provider="gemini", enabled=True, models=("gemini-2.5-flash",)),        ))        client = _groq_lock_client(            tmp_path, monkeypatch,            ScriptedHttpClient({"gemini-2.5-flash": _gemini_response("gemini-fallback")}),            reasoning_config=reasoning_config,        )        monkeypatch.setattr(llm_client_module, "_GROQ_LOCK_FILE", lock_path)        completion = client.complete("system", "user")        assert completion.provider == "gemini"        groq_attempts = [a for a in completion.attempts if a.provider == "groq"]        assert groq_attempts and all(a.status == "lock_timeout" for a in groq_attempts)        assert os.path.exists(lock_path)  # the foreign lock was never deleteddef _gemini_response(marker: str) -> HttpResponse:
    return HttpResponse(
        status_code=200,
        body=json.dumps(
            {
                "candidates": [{"content": {"parts": [{"text": json.dumps({"marker": marker})}]}}],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
            }
        ),
    )


def test_default_config_tries_groq_before_gemini(monkeypatch):
    """platform.json's default order is groq-first, gemini-second — this is now the one
    order shared by both the committee and the lighter per-article news agent, since
    there's a single config-driven chain instead of two hardcoded ones. Groq is primary
    because it has zero observed failures in this project's history and no meaningful
    rate limit; Gemini's free tier is the scarcer resource (previously measured at 22/20
    RPD, 7/5 RPM under real usage) and belongs as the fallback, not the everyday call."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq")})
    client = _client(http)

    completion = client.complete("system", "user")

    assert completion.provider == "groq"
    assert completion.usage.model == "openai/gpt-oss-120b"
    assert len(http.posts) == 1


def test_gemini_router_retries_next_model_on_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient(
        {
            "gemini-3.5-flash": HttpResponse(status_code=429, body="rate limited"),
            "gemini-2.5-flash": _gemini_response("gemini"),
        }
    )
    reasoning_config = _reasoning_config(gemini_models=("gemini-3.5-flash", "gemini-2.5-flash"))
    client = _client(http, reasoning_config)

    completion = client.complete("system", "user")

    assert completion.provider == "gemini"
    assert completion.usage.model == "gemini-2.5-flash"
    assert len(http.posts) == 2
    assert [a.status for a in completion.attempts] == ["429", "SUCCESS"]
    assert [a.model for a in completion.attempts] == ["gemini-3.5-flash", "gemini-2.5-flash"]


def test_permanent_gemini_failure_skips_remaining_models_and_moves_to_groq(monkeypatch):
    """401/403 mean every model behind that key fails identically — don't burn through the
    rest of the Gemini model list, go straight to Groq instead."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient(
        {
            "generativelanguage.googleapis.com": HttpResponse(status_code=401, body="bad key"),
            "api.groq.com": _chat_completion_response("groq"),
        }
    )
    reasoning_config = _reasoning_config(
        gemini_models=("gemini-3.5-flash", "gemini-2.5-flash", "gemini-3-flash"),
        groq_models=("llama-3.3-70b-versatile",),
    )
    client = _client(http, reasoning_config)

    completion = client.complete("system", "user")

    assert completion.provider == "groq"
    gemini_posts = [p for p in http.posts if "generativelanguage" in p]
    assert len(gemini_posts) == 1
    assert len(http.posts) == 2
    assert completion.attempts[0].status == "401"


def test_retryable_gemini_failures_exhaust_every_model_before_falling_back_to_groq(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient(
        {
            "generativelanguage.googleapis.com": HttpResponse(status_code=503, body="busy"),
            "api.groq.com": _chat_completion_response("groq"),
        }
    )
    reasoning_config = _reasoning_config(
        gemini_models=("gemini-3.5-flash", "gemini-2.5-flash"),
        groq_models=("llama-3.3-70b-versatile",),
    )
    client = _client(http, reasoning_config)

    completion = client.complete("system", "user")

    assert completion.provider == "groq"
    gemini_posts = [p for p in http.posts if "generativelanguage" in p]
    assert len(gemini_posts) == 2
    assert len(http.posts) == 3


def test_disabled_provider_is_never_called(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq")})
    reasoning_config = _reasoning_config(
        gemini_models=("gemini-3.5-flash",),
        gemini_enabled=False,
        groq_models=("llama-3.3-70b-versatile",),
    )
    client = _client(http, reasoning_config)

    completion = client.complete("system", "user")

    assert completion.provider == "groq"
    assert len(http.posts) == 1


def test_unsupported_provider_name_is_skipped_without_crashing(monkeypatch):
    """A stale/unrecognized provider entry in config (e.g. a leftover "cerebras" block
    someone pastes back in later) is skipped gracefully, not a crash."""
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq")})
    reasoning_config = AIReasoningConfig(
        providers=(
            LLMProviderConfig(provider="cerebras", models=("gpt-oss-120b",)),
            LLMProviderConfig(provider="groq", models=("llama-3.3-70b-versatile",)),
        )
    )
    client = _client(http, reasoning_config)

    completion = client.complete("system", "user")

    assert completion.provider == "groq"
    assert completion.attempts[0].provider == "cerebras"
    assert completion.attempts[0].status == "unsupported_provider"


def test_all_providers_failing_raises_with_full_attempts_trail(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient(
        {
            "generativelanguage.googleapis.com": HttpResponse(status_code=500, body="gemini down"),
            "api.groq.com": HttpResponse(status_code=500, body="groq down"),
        }
    )
    reasoning_config = _reasoning_config(
        gemini_models=("gemini-3.5-flash", "gemini-2.5-flash"),
        groq_models=("llama-3.3-70b-versatile",),
    )
    client = _client(http, reasoning_config)

    with pytest.raises(AIProviderError) as excinfo:
        client.complete("system", "user")

    # Every model across every provider was tried — a clean raise, not a crash — so the
    # caller (AIResearchDesk.analyze) can degrade to its deterministic committee synthesis.
    assert len(http.posts) == 3
    assert len(excinfo.value.attempts) == 3
    assert all(a.status == "500" for a in excinfo.value.attempts)


def test_provider_attempts_are_recorded_on_a_successful_completion(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient(
        {
            "gemini-3.5-flash": HttpResponse(status_code=503, body="busy"),
            "gemini-2.5-flash": _gemini_response("gemini"),
        }
    )
    reasoning_config = _reasoning_config(gemini_models=("gemini-3.5-flash", "gemini-2.5-flash"))
    client = _client(http, reasoning_config)

    completion = client.complete("system", "user")

    assert len(completion.attempts) == 2
    first, second = completion.attempts
    assert first.provider == "gemini" and first.model == "gemini-3.5-flash"
    assert first.status == "503"
    assert second.status == "SUCCESS" and second.model == "gemini-2.5-flash"
    assert second.latency_ms is not None


def test_gemini_3_models_get_thinking_level_not_thinking_budget(monkeypatch):
    # Gemini 3.x models "think" by default; those tokens are deducted from the same
    # maxOutputTokens budget as the visible answer, and can silently return empty text when
    # the budget runs out mid-thought. Gemini 3.x only accepts thinkingLevel — sending
    # thinkingBudget alongside/instead is a 400 error on this model family.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": _gemini_response("gemini")})
    reasoning_config = _reasoning_config(gemini_models=("gemini-3.5-flash",))
    client = _client(http, reasoning_config)

    client.complete("system", "user")

    sent_body = json.loads(http.bodies[0])
    assert sent_body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}


def test_gemini_2_5_models_get_thinking_budget_zero(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": _gemini_response("gemini")})
    reasoning_config = _reasoning_config(gemini_models=("gemini-2.5-flash",))
    client = _client(http, reasoning_config)

    client.complete("system", "user")

    sent_body = json.loads(http.bodies[0])
    assert sent_body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


def test_gemini_2_0_models_get_no_thinking_config_at_all(monkeypatch):
    # gemini-2.0-flash predates "thinking" and doesn't support the field, so nothing should
    # be sent rather than risk a rejected request on a model that doesn't understand it.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": _gemini_response("gemini")})
    reasoning_config = _reasoning_config(gemini_models=("gemini-2.0-flash",))
    client = _client(http, reasoning_config)

    client.complete("system", "user")

    sent_body = json.loads(http.bodies[0])
    assert "thinkingConfig" not in sent_body["generationConfig"]


def test_gemini_empty_text_from_a_stalled_thinking_response_does_not_crash_the_call(monkeypatch):
    # Reproduces the real failure mode: a 200 response where candidates[0].content.parts[0].text
    # is empty (finishReason MAX_TOKENS hit while still "thinking"). The HTTP layer should not
    # raise for this — it hands back an empty raw_json, and it's the caller's contract
    # validation that correctly rejects it and triggers the deterministic fallback.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    empty_response = HttpResponse(
        status_code=200,
        body=json.dumps(
            {
                "candidates": [
                    {"content": {"parts": [{"text": ""}]}, "finishReason": "MAX_TOKENS"}
                ],
                "usageMetadata": {"promptTokenCount": 500, "candidatesTokenCount": 600},
            }
        ),
    )
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": empty_response})
    reasoning_config = _reasoning_config(gemini_models=("gemini-3.5-flash",))
    client = _client(http, reasoning_config)

    completion = client.complete("system", "user")

    assert completion.provider == "gemini"
    assert completion.raw_json == ""

def _gemini_completion_response(marker: str):
    import json
    from app.application.http import HttpResponse
    return HttpResponse(
        status_code=200,
        body=json.dumps(
            {
                "candidates": [{"content": {"parts": [{"text": json.dumps({"marker": marker})}]}}],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
            }
        ),
    )

def test_permanent_groq_failure_moves_to_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient(
        {
            "api.groq.com": HttpResponse(status_code=404, body="model not found"),
            "generativelanguage": _gemini_completion_response("gemini"),
        }
    )
    client = _client(http)
    completion = client.complete("system", "user")
    assert completion.provider == "gemini"
    assert completion.attempts[0].provider == "groq"
    assert completion.attempts[0].status == "404"
    assert completion.attempts[-1].provider == "gemini"
    assert completion.attempts[-1].status == "SUCCESS"

def test_preferred_provider_falls_back_instead_of_excluding(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient(
        {
            "api.groq.com": HttpResponse(status_code=404, body="model not found"),
            "generativelanguage": _gemini_completion_response("gemini"),
        }
    )
    client = _client(http)
    # The member asks for Groq specifically
    completion = client.complete("system", "user", preferred_provider="groq")
    
    # It should not fail, it should fall back to Gemini
    assert completion.provider == "gemini"
    
    # We should see Groq tried first and failed with 404, not "provider_excluded"
    assert completion.attempts[0].provider == "groq"
    assert completion.attempts[0].status == "404"
    assert completion.attempts[-1].provider == "gemini"
    assert completion.attempts[-1].status == "SUCCESS"== "SUCCESS"


def test_token_guard_dense_json_truncation(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq")})
    client = _client(http)
    
    # 40,000 characters of dense JSON (well over 8000 tokens on typical tokenizer)
    large_json_chunk = '{"key": "value", "arr": [1,2,3]}, '
    large_user_prompt = "{" + (large_json_chunk * 1000) + "}"
    
    assert len(large_user_prompt) > 30000
    
    # Should not raise, but truncate gracefully
    completion = client.complete("system_prompt", large_user_prompt)
    
    # Verify the payload was truncated correctly
    sent_body = json.loads(http.bodies[0])
    sent_user_prompt = sent_body["messages"][1]["content"]
    
    assert len(sent_user_prompt) < len(large_user_prompt)
    assert "[TRUNCATED_BY_GLOBAL_GUARD]" in sent_user_prompt
    
    # Verify the final token estimation falls under 8000 safely
    from app.ai.token_estimate import approx_tokens
    final_tokens = approx_tokens("system_prompt") + approx_tokens(sent_user_prompt)
    assert final_tokens <= 8000


def test_token_guard_small_prompt_untouched(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq")})
    client = _client(http)
    
    small_prompt = '{"hello": "world"}'
    client.complete("system_prompt", small_prompt)
    
    sent_body = json.loads(http.bodies[0])
    sent_user_prompt = sent_body["messages"][1]["content"]
    reasoning_config = _reasoning_config(
        gemini_models=("gemini-3.5-flash", "gemini-2.5-flash"),
        groq_models=("llama-3.3-70b-versatile",),
    )
    client = _client(http, reasoning_config)

    with pytest.raises(AIProviderError) as excinfo:
        client.complete("system", "user")

    # Every model across every provider was tried — a clean raise, not a crash — so the
    # caller (AIResearchDesk.analyze) can degrade to its deterministic committee synthesis.
    assert len(http.posts) == 3
    assert len(excinfo.value.attempts) == 3
    assert all(a.status == "500" for a in excinfo.value.attempts)


def test_provider_attempts_are_recorded_on_a_successful_completion(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient(
        {
            "gemini-3.5-flash": HttpResponse(status_code=503, body="busy"),
            "gemini-2.5-flash": _gemini_response("gemini"),
        }
    )
    reasoning_config = _reasoning_config(gemini_models=("gemini-3.5-flash", "gemini-2.5-flash"))
    client = _client(http, reasoning_config)

    completion = client.complete("system", "user")

    assert len(completion.attempts) == 2
    first, second = completion.attempts
    assert first.provider == "gemini" and first.model == "gemini-3.5-flash"
    assert first.status == "503"
    assert second.status == "SUCCESS" and second.model == "gemini-2.5-flash"
    assert second.latency_ms is not None


def test_gemini_3_models_get_thinking_level_not_thinking_budget(monkeypatch):
    # Gemini 3.x models "think" by default; those tokens are deducted from the same
    # maxOutputTokens budget as the visible answer, and can silently return empty text when
    # the budget runs out mid-thought. Gemini 3.x only accepts thinkingLevel — sending
    # thinkingBudget alongside/instead is a 400 error on this model family.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": _gemini_response("gemini")})
    reasoning_config = _reasoning_config(gemini_models=("gemini-3.5-flash",))
    client = _client(http, reasoning_config)

    client.complete("system", "user")

    sent_body = json.loads(http.bodies[0])
    assert sent_body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}


def test_gemini_2_5_models_get_thinking_budget_zero(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": _gemini_response("gemini")})
    reasoning_config = _reasoning_config(gemini_models=("gemini-2.5-flash",))
    client = _client(http, reasoning_config)

    client.complete("system", "user")

    sent_body = json.loads(http.bodies[0])
    assert sent_body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


def test_gemini_2_0_models_get_no_thinking_config_at_all(monkeypatch):
    # gemini-2.0-flash predates "thinking" and doesn't support the field, so nothing should
    # be sent rather than risk a rejected request on a model that doesn't understand it.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": _gemini_response("gemini")})
    reasoning_config = _reasoning_config(gemini_models=("gemini-2.0-flash",))
    client = _client(http, reasoning_config)

    client.complete("system", "user")

    sent_body = json.loads(http.bodies[0])
    assert "thinkingConfig" not in sent_body["generationConfig"]


def test_gemini_empty_text_from_a_stalled_thinking_response_does_not_crash_the_call(monkeypatch):
    # Reproduces the real failure mode: a 200 response where candidates[0].content.parts[0].text
    # is empty (finishReason MAX_TOKENS hit while still "thinking"). The HTTP layer should not
    # raise for this — it hands back an empty raw_json, and it's the caller's contract
    # validation that correctly rejects it and triggers the deterministic fallback.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    empty_response = HttpResponse(
        status_code=200,
        body=json.dumps(
            {
                "candidates": [
                    {"content": {"parts": [{"text": ""}]}, "finishReason": "MAX_TOKENS"}
                ],
                "usageMetadata": {"promptTokenCount": 500, "candidatesTokenCount": 600},
            }
        ),
    )
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": empty_response})
    reasoning_config = _reasoning_config(gemini_models=("gemini-3.5-flash",))
    client = _client(http, reasoning_config)

    completion = client.complete("system", "user")

    assert completion.provider == "gemini"
    assert completion.raw_json == ""

def _gemini_completion_response(marker: str):
    import json
    from app.application.http import HttpResponse
    return HttpResponse(
        status_code=200,
        body=json.dumps(
            {
                "candidates": [{"content": {"parts": [{"text": json.dumps({"marker": marker})}]}}],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
            }
        ),
    )

def test_permanent_groq_failure_moves_to_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient(
        {
            "api.groq.com": HttpResponse(status_code=404, body="model not found"),
            "generativelanguage": _gemini_completion_response("gemini"),
        }
    )
    client = _client(http)
    completion = client.complete("system", "user")
    assert completion.provider == "gemini"
    assert completion.attempts[0].provider == "groq"
    assert completion.attempts[0].status == "404"
    assert completion.attempts[-1].provider == "gemini"
    assert completion.attempts[-1].status == "SUCCESS"

def test_preferred_provider_falls_back_instead_of_excluding(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient(
        {
            "api.groq.com": HttpResponse(status_code=404, body="model not found"),
            "generativelanguage": _gemini_completion_response("gemini"),
        }
    )
    client = _client(http)
    # The member asks for Groq specifically
    completion = client.complete("system", "user", preferred_provider="groq")
    
    # It should not fail, it should fall back to Gemini
    assert completion.provider == "gemini"
    
    # We should see Groq tried first and failed with 404, not "provider_excluded"
    assert completion.attempts[0].provider == "groq"
    assert completion.attempts[0].status == "404"
    assert completion.attempts[-1].provider == "gemini"
    assert completion.attempts[-1].status == "SUCCESS"


def test_token_guard_dense_json_truncation(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq")})
    client = _client(http)
    
    # 40,000 characters of dense JSON (well over 8000 tokens on typical tokenizer)
    large_json_chunk = '{"key": "value", "arr": [1,2,3]}, '
    large_user_prompt = "{" + (large_json_chunk * 1000) + "}"
    
    assert len(large_user_prompt) > 30000
    
    # Should not raise, but truncate gracefully
    completion = client.complete("system_prompt", large_user_prompt)
    
    # Verify the payload was truncated correctly
    sent_body = json.loads(http.bodies[0])
    sent_user_prompt = sent_body["messages"][1]["content"]
    
    assert len(sent_user_prompt) < len(large_user_prompt)
    assert "[TRUNCATED_BY_GLOBAL_GUARD]" in sent_user_prompt
    
    # Verify the final token estimation falls under 8000 safely
    from app.ai.token_estimate import approx_tokens
    final_tokens = approx_tokens("system_prompt") + approx_tokens(sent_user_prompt)
    assert final_tokens <= 8000


def test_token_guard_small_prompt_untouched(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq")})
    client = _client(http)
    
    small_prompt = '{"hello": "world"}'
    client.complete("system_prompt", small_prompt)
    
    sent_body = json.loads(http.bodies[0])
    sent_user_prompt = sent_body["messages"][1]["content"]
    
    assert sent_user_prompt == small_prompt
    assert "[TRUNCATED" not in sent_user_prompt


def test_opencode_ollama_payloads_do_not_contain_max_tokens(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "test-opencode-key")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-ollama-key")
    
    http = ScriptedHttpClient({
        "opencode.ai/zen": _chat_completion_response("opencode"),
        "ollama.com": _chat_completion_response("ollama")
    })
    
    # Enable opencode and ollama in config
    reasoning_config = AIReasoningConfig(
        providers=(
            LLMProviderConfig(provider="opencode", models=("laguna-s-2.1-free",)),
            LLMProviderConfig(provider="ollama", models=("gpt-oss:120b",)),
        )
    )
    client = _client(http, reasoning_config)
    
    # Force opencode
    client.complete("sys", "user", force_provider="opencode")
    opencode_body = json.loads(http.bodies[0])
    assert "max_tokens" not in opencode_body
    completion = client.complete("system", "user")

    assert len(completion.attempts) == 2
    first, second = completion.attempts
    assert first.provider == "gemini" and first.model == "gemini-3.5-flash"
    assert first.status == "503"
    assert second.status == "SUCCESS" and second.model == "gemini-2.5-flash"
    assert second.latency_ms is not None


def test_gemini_3_models_get_thinking_level_not_thinking_budget(monkeypatch):
    # Gemini 3.x models "think" by default; those tokens are deducted from the same
    # maxOutputTokens budget as the visible answer, and can silently return empty text when
    # the budget runs out mid-thought. Gemini 3.x only accepts thinkingLevel — sending
    # thinkingBudget alongside/instead is a 400 error on this model family.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": _gemini_response("gemini")})
    reasoning_config = _reasoning_config(gemini_models=("gemini-3.5-flash",))
    client = _client(http, reasoning_config)

    client.complete("system", "user")

    sent_body = json.loads(http.bodies[0])
    assert sent_body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}


def test_gemini_2_5_models_get_thinking_budget_zero(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": _gemini_response("gemini")})
    reasoning_config = _reasoning_config(gemini_models=("gemini-2.5-flash",))
    client = _client(http, reasoning_config)

    client.complete("system", "user")

    sent_body = json.loads(http.bodies[0])
    assert sent_body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


def test_gemini_2_0_models_get_no_thinking_config_at_all(monkeypatch):
    # gemini-2.0-flash predates "thinking" and doesn't support the field, so nothing should
    # be sent rather than risk a rejected request on a model that doesn't understand it.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": _gemini_response("gemini")})
    reasoning_config = _reasoning_config(gemini_models=("gemini-2.0-flash",))
    client = _client(http, reasoning_config)

    client.complete("system", "user")

    sent_body = json.loads(http.bodies[0])
    assert "thinkingConfig" not in sent_body["generationConfig"]


def test_gemini_empty_text_from_a_stalled_thinking_response_does_not_crash_the_call(monkeypatch):
    # Reproduces the real failure mode: a 200 response where candidates[0].content.parts[0].text
    # is empty (finishReason MAX_TOKENS hit while still "thinking"). The HTTP layer should not
    # raise for this — it hands back an empty raw_json, and it's the caller's contract
    # validation that correctly rejects it and triggers the deterministic fallback.
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    empty_response = HttpResponse(
        status_code=200,
        body=json.dumps(
            {
                "candidates": [
                    {"content": {"parts": [{"text": ""}]}, "finishReason": "MAX_TOKENS"}
                ],
                "usageMetadata": {"promptTokenCount": 500, "candidatesTokenCount": 600},
            }
        ),
    )
    http = ScriptedHttpClient({"generativelanguage.googleapis.com": empty_response})
    reasoning_config = _reasoning_config(gemini_models=("gemini-3.5-flash",))
    client = _client(http, reasoning_config)

    completion = client.complete("system", "user")

    assert completion.provider == "gemini"
    assert completion.raw_json == ""

def _gemini_completion_response(marker: str):
    import json
    from app.application.http import HttpResponse
    return HttpResponse(
        status_code=200,
        body=json.dumps(
            {
                "candidates": [{"content": {"parts": [{"text": json.dumps({"marker": marker})}]}}],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 3},
            }
        ),
    )

def test_permanent_groq_failure_moves_to_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient(
        {
            "api.groq.com": HttpResponse(status_code=404, body="model not found"),
            "generativelanguage": _gemini_completion_response("gemini"),
        }
    )
    client = _client(http)
    completion = client.complete("system", "user")
    assert completion.provider == "gemini"
    assert completion.attempts[0].provider == "groq"
    assert completion.attempts[0].status == "404"
    assert completion.attempts[-1].provider == "gemini"
    assert completion.attempts[-1].status == "SUCCESS"

def test_preferred_provider_falls_back_instead_of_excluding(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient(
        {
            "api.groq.com": HttpResponse(status_code=404, body="model not found"),
            "generativelanguage": _gemini_completion_response("gemini"),
        }
    )
    client = _client(http)
    # The member asks for Groq specifically
    completion = client.complete("system", "user", preferred_provider="groq")
    
    # It should not fail, it should fall back to Gemini
    assert completion.provider == "gemini"
    
    # We should see Groq tried first and failed with 404, not "provider_excluded"
    assert completion.attempts[0].provider == "groq"
    assert completion.attempts[0].status == "404"
    assert completion.attempts[-1].provider == "gemini"
    assert completion.attempts[-1].status == "SUCCESS"


def test_token_guard_dense_json_truncation(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq")})
    client = _client(http)
    
    # 40,000 characters of dense JSON (well over 8000 tokens on typical tokenizer)
    large_json_chunk = '{"key": "value", "arr": [1,2,3]}, '
    large_user_prompt = "{" + (large_json_chunk * 1000) + "}"
    
    assert len(large_user_prompt) > 30000
    
    # Should not raise, but truncate gracefully
    completion = client.complete("system_prompt", large_user_prompt)
    
    # Verify the payload was truncated correctly
    sent_body = json.loads(http.bodies[0])
    sent_user_prompt = sent_body["messages"][1]["content"]
    
    assert len(sent_user_prompt) < len(large_user_prompt)
    assert "[TRUNCATED_BY_GLOBAL_GUARD]" in sent_user_prompt
    
    # Verify the final token estimation falls under 6500 safely
    from app.ai.token_estimate import approx_tokens
    final_tokens = approx_tokens("system_prompt") + approx_tokens(sent_user_prompt)
    assert final_tokens <= 6500


def test_token_guard_small_prompt_untouched(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    http = ScriptedHttpClient({"api.groq.com": _chat_completion_response("groq")})
    client = _client(http)
    
    small_prompt = '{"hello": "world"}'
    client.complete("system_prompt", small_prompt)
    
    sent_body = json.loads(http.bodies[0])
    sent_user_prompt = sent_body["messages"][1]["content"]
    
    assert sent_user_prompt == small_prompt
    assert "[TRUNCATED" not in sent_user_prompt


def test_opencode_ollama_payloads_do_not_contain_max_tokens(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "test-opencode-key")
    monkeypatch.setenv("OLLAMA_API_KEY", "test-ollama-key")
    
    http = ScriptedHttpClient({
        "opencode.ai/zen": _chat_completion_response("opencode"),
        "ollama.com": _chat_completion_response("ollama")
    })
    
    # Enable opencode and ollama in config
    reasoning_config = AIReasoningConfig(
        providers=(
            LLMProviderConfig(provider="opencode", models=("laguna-s-2.1-free",)),
            LLMProviderConfig(provider="ollama", models=("gpt-oss:120b",)),
        )
    )
    client = _client(http, reasoning_config)
    
    # Force opencode
    client.complete("sys", "user", force_provider="opencode")
    opencode_body = json.loads(http.bodies[0])
    assert "max_tokens" not in opencode_body

    # Force ollama
    client.complete("sys", "user", force_provider="ollama")
    ollama_body = json.loads(http.bodies[1])
    assert "max_tokens" not in ollama_body
    assert ollama_body.get("format") == "json"


from app.domain.ai import AINewsImpactAssessment
from app.ai.committee import _MemberVotePayload
from app.ai.validator import AIJsonValidator

def test_news_analyst_schema_valid():
    v = AIJsonValidator()
    raw = '{"severity": 75, "gold_impact_direction": "BULLISH", "gold_impact_magnitude": 65, "reliability": 90, "reasoning": "x"}'
    res, err = v.validate(raw, AINewsImpactAssessment)
    assert res is not None, err

def test_committee_schema_valid():
    v = AIJsonValidator()
    raw = '{"direction": "LONG", "confidence": 0.82, "reasoning": "x"}'
    res, err = v.validate(raw, _MemberVotePayload)
    assert res is not None, err

def test_malformed_committee_rejected():
    v = AIJsonValidator()
    raw = '{"direction": "UNKNOWN", "confidence": 1.5, "reasoning": "x"}'
    res, err = v.validate(raw, _MemberVotePayload)
    assert res is None

def test_malformed_analyst_rejected():
    v = AIJsonValidator()
    raw = '{"severity": 75, "gold_impact_direction": "UNKNOWN", "gold_impact_magnitude": 65, "reliability": 90, "reasoning": "x"}'
    res, err = v.validate(raw, AINewsImpactAssessment)
    assert res is None

def test_opencode_provider_supports_both_schemas(monkeypatch):
    monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
    def _mock_opencode(sys_prompt):
        import json
        from app.application.http import HttpResponse
        if "news analyst" in sys_prompt.lower():
            content = json.dumps({"severity": 75, "gold_impact_direction": "BULLISH", "gold_impact_magnitude": 65, "reliability": 90, "reasoning": "x"})
        else:
            content = json.dumps({"direction": "LONG", "confidence": 0.82, "reasoning": "x"})
        return HttpResponse(
            status_code=200,
            body=json.dumps({"choices": [{"message": {"content": content}}], "usage": {}})
        )
    
    class DynamicScriptedHttpClient:
        def __init__(self, handler):
            self.handler = handler
            self.bodies = []
            self.posts = []
        def post(self, url, body, headers, timeout_seconds):
            self.bodies.append(body)
            self.posts.append({"url": url})
            sys_prompt = json.loads(body)["messages"][0]["content"]
            return self.handler(sys_prompt)
            
    http = DynamicScriptedHttpClient(_mock_opencode)
    client = _client(http, AIReasoningConfig(providers=[LLMProviderConfig(provider="opencode", models=["test"])]))
    
    # Test News Analyst
    v = AIJsonValidator()
    res1 = client.complete(
        "You are an institutional gold market news analyst...",
        "user",
        force_provider="opencode",
        is_valid=lambda raw: v.validate(raw, AINewsImpactAssessment)[0] is not None
    )
    assert res1 is not None
    assert "BULLISH" in res1.raw_json
    
    # Test Committee Member
    res2 = client.complete(
        "You are one member of an adversarial four-member gold committee...",
        "user",
        force_provider="opencode",
        is_valid=lambda raw: v.validate(raw, _MemberVotePayload)[0] is not None
    )
    assert res2 is not None
    assert "LONG" in res2.raw_json

def test_schema_truncated_json():
    v = AIJsonValidator()
    raw = '{"direction": "LONG", "confidence": 0.82, "reasoning": "This is truncat'
    res, err = v.validate(raw, _MemberVotePayload)
    assert res is None
    assert "JSONDecodeError" in err or "Unterminated string" in err or "Expecting" in err

def test_schema_max_length_violation():
    v = AIJsonValidator()
    raw = json.dumps({
        "direction": "LONG", 
        "confidence": 0.82, 
        "reasoning": "a" * 1600
    })
    res, err = v.validate(raw, _MemberVotePayload)
    assert res is None
    assert "String should have at most" in err

def test_schema_trailing_garbage():
    v = AIJsonValidator()
    raw = '{"direction": "LONG", "confidence": 0.82, "reasoning": "x"} ```'
    res, err = v.validate(raw, _MemberVotePayload)
    assert res is None
    assert "JSONDecodeError" in err or "Extra data" in err

def test_schema_missing_required_field():
    v = AIJsonValidator()
    raw = '{"gold_impact_direction": "BULLISH", "reasoning": "x"}'
    res, err = v.validate(raw, AINewsImpactAssessment)
    assert res is None
    assert "Field required" in err
