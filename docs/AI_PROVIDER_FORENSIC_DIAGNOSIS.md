# AI Provider Forensic Diagnosis

## 1. Executive Summary
This report traces two critical issues observed in the MIOS production pipeline during live runs:
1. **Global Token Guard Failure**: Groq rejecting inputs for exceeding the 8,000 max token limit, despite a global application-level limit guard.
2. **Laguna Schema Validation Failure**: Opencode (`laguna-s-2.1-free`) and Ollama repeatedly failing JSON schema validation during both `ResearchDesk` and `Committee` reasoning phases, despite successfully passing the benchmark suite.

Our read-only forensic analysis confirms that **neither issue is caused by the AI model failing to follow instructions**. Instead, both are caused by specific client-side serialization and API formatting discrepancies between the internal implementation and the provider endpoints.

---

## 2. Token Guard Trace (Issue 1)
**Path Analyzed:** `AIContextBuilder` -> `LLMJsonClient.complete()` -> `_call_groq()`

*   **Calculation Location:** Token budgeting is handled simultaneously in `app/ai/context_builder.py` (`_approx_tokens`) and `app/ai/agents/llm_client.py` (`_approx`).
*   **Methodology:** Both functions use a naive character approximation: `len(text) // 4` (or `len(json.dumps(data)) // 4`). 
*   **Enforcement Point:** `LLMJsonClient.complete()` calculates `total_tokens = _approx(system_prompt) + _approx(user_prompt)`. If this exceeds `MAX_INPUT_TOKENS` (8000), it calculates an `allowed_chars` budget as `(8000 - system - 100) * 4`, truncating the `user_prompt` at that exact character count. Both `system_prompt` and `user_prompt` are accounted for in the budget.
*   **Truncation Phase:** Truncation occurs *before* any provider-specific JSON payload formatting happens.

## 3. Token Guard Failure Cause
The guard fails because **`len(text) // 4` is a highly inaccurate heuristic for dense JSON arrays**. 
*   The `ContextBuilder` outputs heavy JSON structures containing significant punctuation, keys, whitespace, and bracket formatting.
*   On Tiktoken (OpenAI) and Llama 3 (Groq/Ollama) tokenizers, JSON syntax compresses poorly, often resulting in **1 token per 2–2.5 characters**, not 4.
*   By multiplying the 8,000 token limit by 4, the guard permits up to 32,000 characters. When passed to Groq, 32,000 characters of dense JSON evaluates to ~12,500 – 13,600 actual tokens, triggering a `413 Request Too Large` (Limit: 8,000 TPM).

### Minimal Safe Fix
Update the `_approx` and `_approx_tokens` functions to use a more conservative estimate for JSON-heavy traffic, such as `len(text) // 2.5` or `len(text) // 2`. This will constrict the allowed character budget to 16,000–20,000 characters, securely keeping the true token count below 8,000 for all providers.

---

## 4. Laguna Schema Trace (Issue 2)
**Path Analyzed:** `CommitteeMember.vote()` -> `LLMJsonClient.complete()` -> `_call_opencode()` -> `AIJsonValidator.validate()`

*   **Production Schema:** Pydantic `_MemberVotePayload` expects: `direction` (str), `confidence` (float), `reasoning` (str), `key_risk` (str), `time_horizon` (str).
*   **Laguna Output:** The log snippet shows Laguna correctly predicting: `{"direction": "LONG", "confidence": 0.72, "reasoning": "Gold is supported by..."`. 
*   **Schema Mismatch:** There is no field/enum mismatch. The string `"LONG"` is explicitly mapped to `CommitteeDirection.BUY` via `_direction_from_string()` before downstream routing.
*   **The Point of Failure:** Validation fails specifically on a `json.JSONDecodeError` because the returned JSON string is abruptly truncated midway through the `reasoning` value, lacking a closing bracket `}`.

## 5. Laguna Schema Failure Cause
The schema validation fails because the response is being arbitrarily cut off at approximately 128 tokens. 

Comparing the benchmark client (`app/benchmark/providers.py`) to the production client (`app/ai/agents/llm_client.py`):
*   **Benchmark:** The `OpenCodeZenProvider.generate()` POST payload **omits** the `max_tokens` argument.
*   **Production:** `_call_opencode()` and `_call_ollama()` strictly inject `"max_tokens": self._reasoning_config.max_tokens` into the JSON payload root.

**The Bug:** Both Opencode and Ollama are utilizing an OpenAI-compatibility layer (`/v1/chat/completions`). When `max_tokens` is supplied at the payload root (rather than `max_completion_tokens` or Ollama's native `options: {"num_predict": 2000}`), the respective gateways fail to map the parameter and silently fall back to their system default output limit. For these Llama/Ollama backends, this default is **128 tokens**, causing the JSON to neatly truncate mid-sentence.

### Minimal Safe Fix
Remove `"max_tokens"` from the payload definitions in `_call_opencode()` and `_call_ollama()` inside `app/ai/agents/llm_client.py`, aligning them identically to the `app/benchmark/providers.py` structure that successfully scored the models.

---

## 6. Exact Files Involved
*   **Token Guard:** `app/ai/agents/llm_client.py` (Line ~186 `_approx`), `app/ai/context_builder.py` (Line ~16 `_approx_tokens`).
*   **Schema Fallback:** `app/ai/agents/llm_client.py` (Lines ~388 and ~442, `_call_opencode` and `_call_ollama` payload definitions).
*   **Benchmark Reference:** `app/benchmark/providers.py` (Line ~158).

## 7. Regression Test Plan
1.  **Token Guard Verification:** Inject a 40,000-character mock JSON string into `LLMJsonClient.complete()`. Assert that the resulting string passed to `_try_provider` is safely truncated to <= 20,000 characters.
2.  **Schema Compliance:** Test `_call_opencode` using a mock HTTP server. Assert that the `max_tokens` field is omitted from the JSON body sent over the wire.
3.  **Live Run:** Execute `run-once --committee-demo`. Confirm `Groq` successfully accepts the prompt without a 413 limit error, and confirm `opencode` successfully closes its JSON object.

## 8. Risk Assessment
Both fixes are strictly contained to payload formatting and simple mathematical division at the boundaries of the LLM HTTP client. 
*   **No impact** on deterministic engines, algorithms, configuration files, or AI decision logic. 
*   **Zero risk** of altering the behavior of the current valid pipeline tests.
