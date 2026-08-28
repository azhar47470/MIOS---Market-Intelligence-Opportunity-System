import dataclasses
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.application.http import HttpClient
from app.application.platform_config import (
    AIReasoningConfig,
    ApiProviderConfig,
    AuthMode,
    LLMProviderConfig,
)
from app.domain.ai import AIProviderUsage, ProviderAttempt

logger = logging.getLogger("mios.ai")

# Circuit breaker: auto-reset after this many seconds so transient outages don't
# permanently disable a provider for the whole session.
_CIRCUIT_RESET_SECONDS = 600  # 10 minutes

# Retryable failures try the next model within the same provider — the failure looks
# transient (rate limit, server hiccup, garbled output) and a sibling model plausibly
# succeeds. Anything else (401/403, missing credentials, or an otherwise-unlisted 4xx)
# is treated as permanent: every model behind the same API key would fail identically,
# so we skip straight to the next provider instead of burning through the rest of the
# model list.
_RETRYABLE_STATUS = frozenset(
    {"429", "500", "502", "503", "504", "timeout", "invalid_json", "schema_invalid"}
)

_ProviderCall = Callable[
    [str, str, str, float], tuple["LLMJsonCompletion | None", str | None, str]
]

# Groq rate-limit serialization lock. Cross-process lock around Groq calls, since Groq's
# free tier hard-rate-limits concurrent requests. A hard-killed process can leave the
# lock file behind, so acquisition is bounded and clearly stale locks are reclaimed:
#  * 45 s max wait keeps a live demo responsive while covering ordinary queue waits.
#  * 120 s staleness exceeds the worst-case legitimate hold (~3 retries x (30 s HTTP
#    timeout + 5 s capped 429 backoff) ~= 105 s), so a lock that could plausibly belong
#    to an active call is never reclaimed.
_GROQ_LOCK_FILE = os.path.join(tempfile.gettempdir(), "mios_groq.lock")
_GROQ_LOCK_MAX_WAIT_SECONDS = 45.0
_GROQ_LOCK_STALE_AFTER_SECONDS = 120.0
_GROQ_LOCK_POLL_SECONDS = 0.5


def _acquire_groq_lock(
    lock_file: str | None = None,
    *,
    max_wait_seconds: float | None = None,
    stale_after_seconds: float | None = None,
    poll_seconds: float | None = None,
) -> int | None:
    """Acquire the Groq serialization lock with bounded waiting.

    Returns the queue wait time in milliseconds once the lock is held, or ``None`` if the
    lock could not be acquired within ``max_wait_seconds`` and no stale lock could be
    safely reclaimed. Stale detection is conservative: a lock file is only reclaimed after
    the bounded wait has elapsed AND its modification time is older than
    ``stale_after_seconds``. On Windows, ``os.remove`` also fails while another process
    keeps the file open, which provides a second guard against reclaiming an active lock.
    """
    lock_file = _GROQ_LOCK_FILE if lock_file is None else lock_file
    max_wait_seconds = _GROQ_LOCK_MAX_WAIT_SECONDS if max_wait_seconds is None else max_wait_seconds
    stale_after_seconds = (
        _GROQ_LOCK_STALE_AFTER_SECONDS if stale_after_seconds is None else stale_after_seconds
    )
    poll_seconds = _GROQ_LOCK_POLL_SECONDS if poll_seconds is None else poll_seconds
    queue_start = time.perf_counter()
    while True:
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return int((time.perf_counter() - queue_start) * 1000)
        except FileExistsError:
            pass
        if (time.perf_counter() - queue_start) >= max_wait_seconds:
            age = None
            try:
                age = time.time() - os.path.getmtime(lock_file)
            except OSError:
                pass
            if age is not None and age >= stale_after_seconds:
                try:
                    os.remove(lock_file)
                except OSError:
                    pass
                logger.warning(
                    "Reclaimed stale Groq lock (age %.0fs >= %.0fs) at %s",
                    age,
                    stale_after_seconds,
                    lock_file,
                )
                continue
            return None
        time.sleep(poll_seconds)



class AIProviderError(RuntimeError):
    """Raised when no configured LLM provider returns a usable JSON completion."""

    def __init__(self, message: str, attempts: tuple[ProviderAttempt, ...] = ()) -> None:
        super().__init__(message)
        self.attempts = attempts


@dataclass(frozen=True)
class LLMJsonCompletion:
    raw_json: str
    provider: str
    usage: AIProviderUsage
    attempts: tuple[ProviderAttempt, ...] = ()


@dataclass
class _CircuitEntry:
    reason: str
    opened_at: float = field(default_factory=time.monotonic)

    def is_expired(self) -> bool:
        return (time.monotonic() - self.opened_at) >= _CIRCUIT_RESET_SECONDS


class LLMJsonClient:
    """Shared provider client with per-run circuit breaking (with TTL reset) for LLM JSON calls.

    Try-order and try-*what* both come from ``reasoning_config.providers``: each entry names a
    provider ("gemini", "groq") and an ordered list of models for that provider. Every model in
    a provider is tried in order until one succeeds or a permanent failure is hit; if the whole
    provider is exhausted, the client moves to the next provider in the list. This is the one
    provider order used everywhere — the research desk and the lighter per-article news agent
    both build their ``LLMJsonClient`` from the same ``AIReasoningConfig``, so there's a single
    fallback chain to reason about instead of two hardcoded ones.
    """

    def __init__(
        self,
        *,
        http_client: HttpClient,
        groq_config: ApiProviderConfig,
        gemini_config: ApiProviderConfig,
        opencode_config: ApiProviderConfig,
        ollama_config: ApiProviderConfig,
        reasoning_config: AIReasoningConfig,
    ) -> None:
        self._http_client = http_client
        self._groq_config = groq_config
        self._gemini_config = gemini_config
        self._opencode_config = opencode_config
        self._ollama_config = ollama_config
        self._reasoning_config = reasoning_config
        self._provider_failures: dict[str, _CircuitEntry] = {}
        self._calls: dict[str, _ProviderCall] = {
            "groq": self._call_groq,
            "gemini": self._call_gemini,
            "opencode": self._call_opencode,
            "ollama": self._call_ollama,
        }

    def get_provider_chain(self, requires_deep_reasoning: bool = False, preferred_provider: str | None = None) -> list[str]:
        providers_to_try = list(self._reasoning_config.providers)
        if requires_deep_reasoning:
            providers_to_try.sort(key=lambda p: p.provider != "opencode")
        elif preferred_provider is not None:
            providers_to_try.sort(key=lambda p: p.provider != preferred_provider)
        return [p.provider for p in providers_to_try if p.enabled]

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        is_valid: Callable[[str], bool] | None = None,
        requires_deep_reasoning: bool = False,
        preferred_provider: str | None = None,
        force_provider: str | None = None,
        temperature: float | None = None,
    ) -> LLMJsonCompletion:
        import logging
        logger = logging.getLogger(__name__)
        """Get a completion from the first available provider/model, in provider/model order.

        If ``is_valid`` is given, a response that fails it (e.g. a caller's Pydantic schema
        check) is treated the same as an HTTP-level failure.

        ``preferred_provider`` orders the chain to try the named provider first (used by the
        adversarial committee so each member's voice defaults to one provider). If it fails,
        the client proceeds to the next configured provider instead of outright failing.
        ``temperature`` overrides the shared ``AIReasoningConfig`` temperature for this
        call, so committee members can keep distinct decision styles.
        """
        effective_temperature = (
            temperature
            if temperature is not None
            else self._reasoning_config.temperature
        )
        
        # 2. Add a final global LLM request guard
        from app.ai.token_estimate import approx_tokens
        MAX_INPUT_TOKENS = 8000
        SAFE_INPUT_BUDGET = 6500
        
        system_tokens = approx_tokens(system_prompt)
        user_tokens = approx_tokens(user_prompt)
        
        if system_tokens + user_tokens > SAFE_INPUT_BUDGET:
            # Calculate how many tokens we can allow for user_prompt
            # Leave a small buffer of 50 tokens
            allowed_user_tokens = max(0, SAFE_INPUT_BUDGET - system_tokens - 50)
            
            if allowed_user_tokens > 0:
                # Convert token budget back to approximate characters (reverse of // 1.5)
                # But to be safe and deterministic, let's just slice directly based on the character ratio
                allowed_chars = int(allowed_user_tokens * 1.5)
                marker = "\n...[TRUNCATED_BY_GLOBAL_GUARD]"
                # Leave room for the marker
                safe_chars = max(0, allowed_chars - len(marker))
                user_prompt = user_prompt[:safe_chars] + marker
            else:
                user_prompt = ""
                
            # Final safety check against safe budget, but MAX_INPUT_TOKENS is absolute ceiling
            final_tokens = approx_tokens(system_prompt) + approx_tokens(user_prompt)
            if final_tokens > SAFE_INPUT_BUDGET:
                # Truncate even more aggressively if the heuristic failed
                overflow = final_tokens - SAFE_INPUT_BUDGET
                reduce_chars = int((overflow + 50) * 1.5)
                marker = "\n...[TRUNCATED_BY_GLOBAL_GUARD]"
                user_prompt = user_prompt[:-reduce_chars - len(marker)] + marker
                
            if approx_tokens(system_prompt) + approx_tokens(user_prompt) > MAX_INPUT_TOKENS:
                raise AIProviderError("Input strictly exceeds MAX_INPUT_TOKENS even after global guard compression.")
        attempts: list[ProviderAttempt] = []
        providers_to_try = list(self._reasoning_config.providers)
        if force_provider:
            providers_to_try = [p for p in providers_to_try if p.provider == force_provider]
        else:
            if requires_deep_reasoning:
                providers_to_try.sort(key=lambda p: p.provider != "opencode")
            elif preferred_provider is not None:
                providers_to_try.sort(key=lambda p: p.provider != preferred_provider)
            
        if not force_provider:
            logger.info(f'[COMMITTEE] Selected primary provider = {providers_to_try[0].provider if providers_to_try else "None"}')

        for provider_cfg in providers_to_try:
            if not provider_cfg.enabled:
                continue
            call = self._calls.get(provider_cfg.provider)
            if call is None:
                attempts.append(
                    ProviderAttempt(
                        provider=provider_cfg.provider,
                        status="unsupported_provider",
                        error=f"No LLM call is implemented for provider {provider_cfg.provider!r}.",
                    )
                )
                continue
            # Check circuit breaker — auto-reset after TTL. Circuit-broken at the provider
            # level (not per model): if every model in a provider was exhausted last cycle,
            # there's little point re-trying all of them again within the reset window.
            entry = self._provider_failures.get(provider_cfg.provider)
            if entry is not None:
                if entry.is_expired():
                    logger.info(
                        "LLM circuit breaker for %s reset after timeout.", provider_cfg.provider
                    )
                    del self._provider_failures[provider_cfg.provider]
                else:
                    attempts.append(
                        ProviderAttempt(
                            provider=provider_cfg.provider,
                            status="circuit_open",
                            error=entry.reason,
                        )
                    )
                    continue
            completion, provider_attempts = self._try_provider(
                provider_cfg,
                call,
                system_prompt,
                user_prompt,
                is_valid,
                effective_temperature,
            )
            attempts.extend(provider_attempts)
            if completion is not None:
                return dataclasses.replace(completion, attempts=tuple(attempts))
            last_attempt = provider_attempts[-1] if provider_attempts else None
            reason = last_attempt.error if last_attempt else "unknown provider error"
            self._provider_failures[provider_cfg.provider] = _CircuitEntry(
                reason=_truncate_error(reason or "unknown provider error")
            )
            logger.warning(
                "LLM provider %s unavailable after %d model attempt(s): %s",
                provider_cfg.provider,
                len(provider_attempts),
                reason,
            )
        summary = "; ".join(f"{a.provider}/{a.model or '-'}: {a.status}" for a in attempts)
        raise AIProviderError(summary or "No LLM provider is configured", attempts=tuple(attempts))

    def _try_provider(
        self,
        provider_cfg: LLMProviderConfig,
        call: _ProviderCall,
        system_prompt: str,
        user_prompt: str,
        is_valid: Callable[[str], bool] | None,
        temperature: float,
    ) -> tuple[LLMJsonCompletion | None, list[ProviderAttempt]]:
        attempts: list[ProviderAttempt] = []
        import logging
        logger = logging.getLogger(__name__)
        for model in provider_cfg.models:
            logger.info(f'[COMMITTEE] Selected model = {model}')
            logger.info(f'[COMMITTEE] Calling LLM provider = {provider_cfg.provider}')
            started_at = time.perf_counter()
            completion, error, status = call(system_prompt, user_prompt, model, temperature)
            if completion:
                logger.info(f'[COMMITTEE] LLM response received = {status}')
            latency_ms = int((time.perf_counter() - started_at) * 1000)
            is_schema_valid = is_valid is None or (
                completion is not None and is_valid(completion.raw_json)
            )
            if completion is not None and not is_schema_valid:
                logger.warning(f"Schema validation failed. Raw response snippet: {completion.raw_json[:500]}")
                completion = None
                error = "response did not match the expected schema"
                status = "schema_invalid"
            if completion is not None:
                attempts.append(
                    ProviderAttempt(
                        provider=provider_cfg.provider,
                        model=model,
                        status="SUCCESS",
                        latency_ms=latency_ms,
                    )
                )
                return completion, attempts
            attempts.append(
                ProviderAttempt(
                    provider=provider_cfg.provider,
                    model=model,
                    status=status,
                    latency_ms=latency_ms,
                    error=_truncate_error(error or "unknown error"),
                )
            )
            if status not in _RETRYABLE_STATUS:
                logger.info(
                    "%s/%s failed with permanent status %s; skipping remaining models for "
                    "this provider.",
                    provider_cfg.provider,
                    model,
                    status,
                )
                break
        return None, attempts

    def _call_groq(
        self, system_prompt: str, user_prompt: str, model: str, temperature: float
    ) -> tuple[LLMJsonCompletion | None, str | None, str]:
        import os, tempfile, re
        api_key = _api_key(self._groq_config)
        if api_key is None:
            return (
                None,
                f"Required environment variable {self._groq_config.api_key_env} is not set.",
                "missing_api_key",
            )
        payload = {
            "model": model,
            "temperature": temperature,
            "max_tokens": self._reasoning_config.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        
        lock_queue_wait_ms = _acquire_groq_lock(_GROQ_LOCK_FILE)
        if lock_queue_wait_ms is None:
            return (
                None,
                f"Groq serialization lock at {_GROQ_LOCK_FILE} could not be acquired within "
                f"{_GROQ_LOCK_MAX_WAIT_SECONDS:g}s and does not look stale.",
                "lock_timeout",
            )
        queue_wait_ms = lock_queue_wait_ms
        
        retries = 0
        started_at = time.perf_counter()
        try:
            while retries < 3:
                try:
                    response = self._http_client.post(
                        _endpoint_url(self._groq_config, "chat_completions"),
                        body=json.dumps(payload),
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        timeout_seconds=self._groq_config.timeout_seconds,
                    )
                except TimeoutError as error:
                    return None, str(error), "timeout"
                except Exception as error:
                    return None, str(error), "network_error"
                
                if response.status_code == 429:
                    retries += 1
                    match = re.search(r'try again in ([\d\.]+)s', response.body)
                    wait_time = float(match.group(1)) + 0.1 if match else 2.0
                    time.sleep(min(wait_time, 5.0))  # sleep max 5 seconds
                    continue
                break
            
            runtime_ms = int((time.perf_counter() - started_at) * 1000)
            if response.status_code >= 400:
                return None, response.body, str(response.status_code)
        finally:
            try:
                os.remove(_GROQ_LOCK_FILE)
            except OSError:
                pass
        try:
            data = json.loads(response.body)
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return (
                LLMJsonCompletion(
                    raw_json=_extract_json(str(content)),
                    provider="groq",
                    usage=AIProviderUsage(
                        provider="groq",
                        model=model,
                        prompt_tokens=int(usage.get("prompt_tokens") or 0),
                        completion_tokens=int(usage.get("completion_tokens") or 0),
                        runtime_ms=runtime_ms,
                        retry_count=retries,
                        queue_wait_ms=queue_wait_ms,
                    ),
                ),
                None,
                "SUCCESS",
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            return None, f"Invalid Groq response: {error}", "invalid_json"


    def _call_opencode(
        self, system_prompt: str, user_prompt: str, model: str, temperature: float
    ) -> tuple[LLMJsonCompletion | None, str | None, str]:
        api_key = _api_key(self._opencode_config)
        if api_key is None:
            return None, 'Missing OPENCODE_API_KEY', 'missing_api_key'
        payload = {
            'model': model,
            'temperature': temperature,
            'response_format': {'type': 'json_object'},
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
        }
        import time
        started_at = time.perf_counter()
        try:
            response = self._http_client.post(
                _endpoint_url(self._opencode_config, 'chat_completions'),
                body=json.dumps(payload),
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                timeout_seconds=self._opencode_config.timeout_seconds,
            )
        except Exception as e:
            return None, str(e), 'network_error'
        runtime_ms = int((time.perf_counter() - started_at) * 1000)
        if response.status_code != 200:
            return None, response.body, str(response.status_code)
        try:
            data = json.loads(response.body)
            content = data['choices'][0]['message']['content']
            usage = data.get('usage', {})
            return LLMJsonCompletion(
                raw_json=_extract_json(str(content)),
                provider='opencode',
                usage=AIProviderUsage(
                    provider='opencode',
                    model=model,
                    prompt_tokens=int(usage.get('prompt_tokens', 0)),
                    completion_tokens=int(usage.get('completion_tokens', 0)),
                    runtime_ms=runtime_ms,
                ),
            ), None, 'SUCCESS'
        except Exception as error:
            return None, f"Invalid response: {error}", "invalid_json"

    def _call_ollama(
        self, system_prompt: str, user_prompt: str, model: str, temperature: float
    ) -> tuple[LLMJsonCompletion | None, str | None, str]:
        api_key = _api_key(self._ollama_config)
        if api_key is None:
            return None, 'Missing OLLAMA_API_KEY', 'missing_api_key'
        payload = {
            'model': model,
            'temperature': temperature,
            'format': 'json',
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
        }
        import time
        started_at = time.perf_counter()
        try:
            response = self._http_client.post(
                _endpoint_url(self._ollama_config, 'chat_completions'),
                body=json.dumps(payload),
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                timeout_seconds=self._ollama_config.timeout_seconds,
            )
        except Exception as e:
            return None, str(e), 'network_error'
        runtime_ms = int((time.perf_counter() - started_at) * 1000)
        if response.status_code != 200:
            return None, response.body, str(response.status_code)
        try:
            data = json.loads(response.body)
            if 'choices' in data:
                content = data['choices'][0]['message']['content']
                usage = data.get('usage', {})
                prompt_tokens = usage.get('prompt_tokens', 0)
                completion_tokens = usage.get('completion_tokens', 0)
            elif 'message' in data:
                content = data['message']['content']
                prompt_tokens = data.get('prompt_eval_count', 0)
                completion_tokens = data.get('eval_count', 0)
            else:
                raise KeyError("No choices or message key in Ollama response")
                
            # Fallbacks for usage
            return LLMJsonCompletion(
                raw_json=_extract_json(str(content)),
                provider='ollama',
                usage=AIProviderUsage(
                    provider='ollama',
                    model=model,
                    prompt_tokens=int(prompt_tokens),
                    completion_tokens=int(completion_tokens),
                    runtime_ms=runtime_ms,
                ),
            ), None, 'SUCCESS'
        except Exception as error:
            return None, f"Invalid response: {error}", "invalid_json"

    def _call_gemini(
        self, system_prompt: str, user_prompt: str, model: str, temperature: float
    ) -> tuple[LLMJsonCompletion | None, str | None, str]:
        api_key = _api_key(self._gemini_config)
        if api_key is None:
            return (
                None,
                f"Required environment variable {self._gemini_config.api_key_env} is not set.",
                "missing_api_key",
            )
        # Use proper system_instruction field for role separation (fixes prompt quality issue)
        payload = {
            "systemInstruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}],
                }
            ],
            "generationConfig": _gemini_generation_config(
                self._reasoning_config, model, temperature
            ),
        }
        started_at = time.perf_counter()
        try:
            response = self._http_client.post(
                _endpoint_url(self._gemini_config, "generate_content", model=model),
                body=json.dumps(payload),
                params=_auth_params(self._gemini_config),
                headers={"Content-Type": "application/json"},
                timeout_seconds=self._gemini_config.timeout_seconds,
            )
        except TimeoutError as error:
            return None, str(error), "timeout"
        except Exception as error:
            return None, str(error), "network_error"
        runtime_ms = int((time.perf_counter() - started_at) * 1000)
        if response.status_code >= 400:
            return None, response.body, str(response.status_code)
        try:
            data = json.loads(response.body)
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            usage = data.get("usageMetadata", {})
            return (
                LLMJsonCompletion(
                    raw_json=_extract_json(str(content)),
                    provider="gemini",
                    usage=AIProviderUsage(
                        provider="gemini",
                        model=model,
                        prompt_tokens=int(usage.get("promptTokenCount") or 0),
                        completion_tokens=int(usage.get("candidatesTokenCount") or 0),
                        runtime_ms=runtime_ms,
                    ),
                ),
                None,
                "SUCCESS",
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
            return None, f"Invalid Gemini response: {error}", "invalid_json"


def _api_key(config: ApiProviderConfig) -> str | None:
    if config.api_key_env is None:
        return None
    value = os.getenv(config.api_key_env)
    return value or None


def _auth_params(config: ApiProviderConfig) -> dict[str, str]:
    if config.auth_mode != AuthMode.QUERY_PARAM or config.api_key_param is None:
        return {}
    api_key = _api_key(config)
    return {config.api_key_param: api_key} if api_key else {}


def _gemini_generation_config(
    reasoning_config: AIReasoningConfig, model: str, temperature: float
) -> dict[str, object]:
    config: dict[str, object] = {
        "temperature": temperature,
        "maxOutputTokens": reasoning_config.max_tokens,
    }
    thinking_config = _gemini_thinking_config(model)
    if thinking_config is not None:
        config["thinkingConfig"] = thinking_config
    return config


def _gemini_thinking_config(model: str) -> dict[str, object] | None:
    """Gemini 2.5+/3.x models "think" by default, and those thinking tokens are deducted
    from the same maxOutputTokens budget as the visible answer — when the budget runs out
    mid-thought, the visible text comes back empty (a documented Gemini API behavior, not a
    bug in this client). This keeps that from silently consuming the whole budget.

    Gemini 3.x uses ``thinkingLevel``; Gemini 2.5.x uses ``thinkingBudget`` (0 disables it
    outright). Sending both in the same request is a 400 error, so exactly one is chosen based
    on the model name. Older, non-thinking models (e.g. gemini-2.0-flash) don't support this
    field at all, so nothing is sent for anything outside the two known families.
    """
    if model.startswith("gemini-3"):
        return {"thinkingLevel": "LOW"}
    if model.startswith("gemini-2.5"):
        return {"thinkingBudget": 0}
    return None



def _extract_json(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```json"):
        stripped = stripped[7:]
    if stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    stripped = stripped.strip()
    # Extract outermost JSON object
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end >= start:
        return stripped[start : end + 1]
    return stripped


def _truncate_error(value: str) -> str:
    return value[:1000]


def _endpoint_url(config, endpoint_name: str, **values: str) -> str:
    endpoint = config.endpoints[endpoint_name]
    path = endpoint.path.format(**values)
    return f"{config.base_url.rstrip('/')}{path}"

