# Merge patch — 2026-07-30

Base: `azhargpt` (the most current of the three folders compared: `azhargpt`,
`podcaster/Gold intelligent analysis platform`, `azhar55/Gold intelligent analysis platform`).
This patch restores several fixes that existed in the `azhar55` copy but were lost along the
way, and adds a couple of new defensive fixes on top. Every change below was verified with
`python -m compileall` and cross-checked against the existing test suite; stale tests that
encoded the old (regressed) behavior were updated to match.

## Restored fixes (previously existed, were lost in a later edit)

1. **`app/application/market_data_collector.py`** — back to one combined GDELT query for
   both the news and geopolitical engines instead of two near-identical queries. This was
   the confirmed root cause of repeated GDELT rate-limit rejections, not just a cooldown
   timing issue.
2. **`app/infrastructure/providers/gdelt_provider.py`** — cooldown restored to 20s
   (from 5s) and persisted to `data/gdelt_cooldown.json` using wall-clock time, so a
   fresh `run-once` process remembers the previous invocation's request timing instead
   of starting from zero every time.
3. **`app/infrastructure/providers/base.py`** — an empty response body is now reported
   as a clean `NO_DATA` status instead of raising a raw `JSONDecodeError`.
4. **`app/application/discord_embed_formatter.py`** — `_truncate` uses
   `max(0, limit - 3)` again, with the comment explaining why (a prior version ran
   `limit + 2` characters over on every truncation).
5. **`app/ai/research_desk.py`** — `_deterministic_report()` no longer caps specialist
   confidence at 35 or labels the report `AI-FALLBACK-`. Building specialist reports
   straight from deterministic engine output is the normal path now, not a degraded
   fallback, so it uses real confidence, a `DET-` report ID, and `fallback_reason=None`.
6. **`app/ai/agents/research_agents.py`** — the committee system prompt again tells the
   model explicitly that `disagreements`, `missing_evidence`, `weak_evidence`,
   `conflicting_evidence`, `required_confirmations`, and `alternative_scenarios` must be
   flat arrays of strings, never an object — with an example. This is what was silently
   missing when Gemini started grouping `alternative_scenarios` into a
   `{"Bullish Reversal": "...", ...}`-shaped object and failing contract validation.
7. **`app/application/platform_config.py`** and **`config/platform.json`** — default LLM
   order restored to Groq-first, Gemini-second. Both files needed the change; the JSON
   file overrides the Python default at runtime.

## New fixes (none of the three copies had these)

8. **`app/domain/ai.py`** — `CommitteeReportPayload` now has a `field_validator` that
   flattens a dict into a string list for the same six fields covered by fix #6, as
   defense-in-depth. Prompting alone hasn't reliably stopped this failure mode; this
   means a stray dict-shaped response no longer hard-fails contract validation.
9. **`app/ai/agents/llm_client.py`** — `complete()` accepts an optional `is_valid`
   callback again. A response that fails it is now treated the same as an HTTP failure:
   the next model in that provider is tried, then the next provider — instead of
   returning a syntactically-valid-but-schema-wrong response as a false success and
   exiting the whole fallback chain early. Wired into both the committee call
   (`research_agents.py`) and the per-article news call (`news_analyst.py`).

## Left alone (kept from the newest copy, verified correct)

- FRED-only DXY sourcing (dead TwelveData endpoint removed) — `dxy_provider.py`,
  `providers/factory.py`, `twelve_data_provider.py`.
- Geopolitical keyword-fallback enrichment using article-clustering topics and
  high-risk-country flags — `geopolitical_engine.py`.
- `ProviderAttempt` audit trail and multi-model-per-provider fallback within Gemini —
  `llm_client.py`, `domain/ai.py`.
- PMI/`NAPM` macro series — `fundamental_engine.py`.
- Centralized default `User-Agent` header on the shared HTTP client (a genuine
  improvement over the older per-provider duplication, not a regression).
- The core `decision_engine.py` — byte-identical across all three copies, untouched here.

## Test suite

- `tests/test_llm_client_providers.py` — the test asserting Gemini-first as the default
  order was rewritten to assert Groq-first (renamed
  `test_default_config_tries_groq_before_gemini`).
- `tests/test_ai_research_desk.py` — the assertion that deterministic specialist reports
  always carry a `fallback_reason` was inverted to assert `is None`, matching fix #5.
- `tests/test_provider_repository_scheduler.py` — the four tests that instantiate
  `GDELTProvider` now pass `cooldown_state_path=tmp_path / "gdelt_cooldown.json"` so they
  don't read or write the real `data/gdelt_cooldown.json`, and the two that assert on
  sleep duration now expect `20.0` instead of `5.0`.
- `tests/test_ai_news_agent.py` — one stale comment describing the (now-reverted)
  Gemini-first default was corrected; the test itself builds its own explicit
  `reasoning_config` and didn't need a logic change.

None of these could be executed in the environment this patch was written in (no network
access to install `pydantic`/`pytest`), so this was verified by full-project
`python -m compileall` plus a manual trace of every changed function and its call sites,
not by an actual test run. Run the suite for real before merging.
