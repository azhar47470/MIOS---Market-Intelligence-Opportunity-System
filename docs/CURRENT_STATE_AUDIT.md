# MIOS Current-State Forensic Audit

**Date:** 2026-08-28 · **Scope:** read-only forensic snapshot of `mios_hackathon_final` · **No source modifications were made** (this file is the only new artifact, created per audit instructions).

---

## A. Current Repository State

| Item | Finding |
|---|---|
| Repository root | `c:\Users\azhar\OneDrive\Desktop\Anitgravity D\mios_hackathon_final` |
| Git repository | **NO — no `.git` directory exists.** `git` reports "not a git repository". |
| Current branch | N/A (no git) |
| Latest 10 commits | N/A (no git history) |
| git status / staged / untracked | N/A (no git). `.gitignore` exists but is inert. |
| Merge conflicts | None detectable (no git state, no conflict markers found in source). |
| Temporary/generated files | **Yes — many** (see Section J): `.pytest_cache/`, `.pytest_tmp/` (27 test artifact dirs), `__pycache__/`, `.venv/`, `logs/mios.log`, `data/e2e_*.db`, `data/mios.db(-shm/-wal)`, `data/gdelt_cooldown.json`, `data/paper_trading.json`, `latest.json`, root-level empty `mios.db` (0 bytes), `scratch.py`, `scratch_js.js`, 5 dashboard backup files, `data/benchmark_results/raw/*` (~350 generated result files). |

**Key finding: the canonical hackathon codebase has no version control.** Any future destructive change is unrecoverable.

---

## B. Current Test Baseline

Command: `python -m pytest -q`

| Metric | Value |
|---|---|
| Total tests | **231** |
| Passed | **231** |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| Execution time | **43.93 s** |

Full suite is green. No failures to diagnose.

---

## C. Architecture Map

### C.1 Layers

| Layer | Location | Primary entry points | Responsibility |
|---|---|---|---|
| Domain | `app/domain/` | `common.py`, `intelligence.py`, `decisions.py`, `ai.py`, `market_data.py`, `features.py`, `enums.py`, `notification_models.py` | Pure pydantic contracts: `EvidenceRecord`, `RiskRecord`, `DecisionReport`, `AnalysisBundle`, `UnifiedDecision`, `PullbackRiskReport`, `TechnicalFeatureSet`, AI report contracts. |
| Application | `app/application/` | `orchestrator.py` → `GoldIntelligenceOrchestrator` | Pipeline orchestration, engines, adapters, policy, configs, journals, notifications. |
| Infrastructure | `app/infrastructure/` | `providers/factory.py` → `build_provider_runtime` | HTTP (`urllib_http_client`), market/news/macro providers, repositories (JSON + SQLite journals), Discord webhook, config loader. |
| AI | `app/ai/` | `research_desk.py` → `AIResearchDesk`, `committee.py` → `AdversarialCommittee`, `agents/llm_client.py` → `LLMJsonClient` | Context building, RAG, committee voting, provider chain, validation. |
| Presentation | `app/presentation/dashboard.py` | `serve_dashboard`, `write_static_dashboard` | Stdlib-HTTP dashboard (not Flask despite `warn_if_insecure_flask_secret` name). |
| CLI / composition root | `app/main.py` | `main()` | argparse subcommands: `run-once` (`--mode forex|physical|etf|json`, `--committee-demo`), `run-forever`, `serve`, `export-dashboard`, `backtest`, `price`. |
| Scheduling | `app/scheduler/` | `continuous_runner.py`, `polling_scheduler.py` | Interval loop for `run-forever`. |
| Contracts | `contracts/schemas/` + `app/contracts/registry.py` | JSON Schema registry | 24 schema files for all domain envelopes. |

### C.2 Component inventory

| Component | File | Class/function | Responsibility / key dependencies |
|---|---|---|---|
| Orchestration | `app/application/orchestrator.py` | `GoldIntelligenceOrchestrator.run_once` | Collect → engines → research desk → filters → decision → unified → mode policy → adapters → journal/notify/paper-trade. Depends on every engine + `UnifiedDecisionBuilder` + `ModeExecutionPolicy`. |
| Technical engine | `app/application/engines/technical_engine.py` | `TechnicalIntelligenceEngine.analyze_features` | Score/bias/evidence/support-resistance/expected move from `TechnicalFeatureSet`. |
| Feature computation | `app/features/technical_features.py` | `build_technical_features` | All indicator math (RSI, EMA, ATR, SMC/FVG, sweeps, MTF…). |
| Fundamental engine | `app/application/engines/fundamental_engine.py` | `FundamentalIntelligenceEngine.analyze` | DXY, calendar, macro series → macro bias. |
| Institutional engine | `app/application/engines/institutional_engine.py` | `InstitutionalIntelligenceEngine.analyze` | COT + GLD flows → positioning bias. |
| News engine | `app/application/engines/news_engine.py` | `NewsIntelligenceEngine.analyze` | Keyword scoring; optional direct AI call via `GroqNewsAnalystAgent` when specialist report is non-fallback. |
| Geopolitical engine | `app/application/engines/geopolitical_engine.py` | `GeopoliticalIntelligenceEngine.analyze` | Risk-term scoring; same optional-AI pattern. |
| Regime engine | `app/application/engines/regime_engine.py` | `MarketRegimeEngine.analyze` | Classifies regime (EVENT_DRIVEN > RISK_OFF > HIGH_VOLATILITY > LOW_VOLATILITY > BULL > BEAR > RANGE); emits `dynamic_weights` from config. |
| PullbackRiskEngine | `app/application/engines/pullback_risk_engine.py` | `PullbackRiskEngine.analyze`, `report_to_evidence` | Informational pullback score → evidence records (see Section F). |
| Decision engine | `app/application/engines/decision_engine.py` | `DecisionEngine.decide`, `OpportunityFilter.assess`, `InvestmentScoringEngine.score` | Discipline gates, weighted scoring, Bayesian confidence trace, recommendation. |
| OpportunityFilter | same file (line 23) | `OpportunityFilter` | Global gates: aggregate confidence ≥ `minimum_confidence_for_action` (60) and high-severity risk count ≤ `max_high_severity_risks_for_action` (1); blockers cost 15 score points each. |
| ModeExecutionPolicy | `app/application/execution_policy.py` | `ModeExecutionPolicy.evaluate` | Mode-specific gates (see Section E). Hard rules: NEUTRAL bias and HIGH/CRITICAL risks can never be overridden. |
| Unified decision | `app/application/adapters/unified.py` | `UnifiedDecisionBuilder.build` | Maps recommendation → market bias + narratives/evidence/votes for adapters. |
| Physical adapter | `app/application/adapters/physical.py` | `PhysicalGoldAdapter.adapt` | Allocation/conviction/horizon/thesis for physical gold. |
| Forex adapter | `app/application/adapters/forex.py` | `ForexAdapter.adapt` | LONG/SHORT/WAIT signal + fixed-pct TP/SL (target 4%, stop 2%). |
| ETF adapter | `app/application/adapters/etf.py` | `GoldETFAdapter.adapt` | GLD/IAU/GLDM vehicle guidance + allocation. |
| AI committee | `app/ai/committee.py` | `AdversarialCommittee.deliberate` | 4 members: Deterministic Anchor (0.25), Macro Strategist (0.30), Tactical Trader (0.25), Contrarian Risk (0.20); weighted consensus → `InvestmentCommitteeReport`. |
| AI provider chain | `app/ai/agents/llm_client.py` | `LLMJsonClient.complete`, `get_provider_chain` | Single shared provider client with circuit breakers, token guard, retries. |
| ContextBuilder | `app/ai/context_builder.py` | `AIContextBuilder.for_research_desk` | Budgeted evidence ranking/selection (max_tokens=7000) + telemetry. |
| RAG | `app/ai/rag.py` | `KnowledgeRetriever.enrich` | Keyword retrieval over `knowledge/` (currently README-only content). |
| Provider routing (data) | `app/infrastructure/providers/factory.py` | `build_provider_runtime` | Wires TwelveData, FRED (macro/calendar/DXY), COT, GLD, GDELT, NewsAPI, RSS + caching repositories into `RepositoryBackedMarketDataCollector`. |
| News provider cascade | `app/infrastructure/repositories/provider_repositories.py` | `ProviderNewsEventRepository` | GDELT → connector (marketaux/thenewsapi/worldnewsapi) → NewsAPI → RSS fallbacks with per-source TTLs and cooldown. |
| Telemetry | orchestrator `pipeline_telemetry`; `AIProviderUsage`; context `_telemetry` | — | Engine runtimes, provider attempts/tokens/latency, context budget stats. |
| Validation | `app/ai/validator.py` | `AIJsonValidator.validate` | Pydantic validation of every LLM JSON payload. |
| Benchmark | `app/benchmark/` (`harness.py`, `providers.py`, `reporting.py`, `scenarios.py`, `scoring.py`) + `scripts/benchmark_committee.py` | Benchmark harness | Scenario-driven LLM scoring (12 scenarios in `data/benchmark_scenarios/`). |
| Paper trading | `app/paper_trading/` | `PaperTradingEngine` | Virtual position tracking from decisions. |
| Backtesting | `app/application/backtesting.py` + `app/backtesting/` | `BacktestingEngine.run` | Replay decision logic over historical bars. |

---

## D. Current AI Provider Path (verified in code, not assumed)

| Item | Current state |
|---|---|
| Chain order | Defined by `config/platform.json` `ai_reasoning.providers`: **1) groq [`openai/gpt-oss-120b`] → 2) opencode [`laguna-s-2.1-free`] → 3) ollama [`gpt-oss:120b`] → 4) gemini [`gemini-3.5-flash`, `gemini-3.1-flash-lite`]** (all enabled). |
| Primary provider / model | **Groq / `openai/gpt-oss-120b`**. All three LLM committee members are Groq-pinned (`committee.py` lines 239–262) with temperatures 0.4 / 0.5 / 0.6. |
| Escalation conditions | `AIResearchDesk._evaluate_escalation`: regime confidence < 40%, regime ≠ NORMAL, geopolitical score < 30, \|technical − fundamental\| > 60, technical score within ±10 of 50, or CRITICAL opposing evidence. Escalation sorts the chain so **opencode (Laguna) is tried first** (`requires_deep_reasoning`). ⚠ The "CRITICAL opposing evidence" check reads `ev.direction.value`, but `EvidenceRecord` has **no `direction` field** — latent `AttributeError` (see Section J). |
| OpenCode / Laguna | `https://opencode.ai/zen/v1/chat/completions`, `OPENCODE_API_KEY`, model `laguna-s-2.1-free`; used as escalation-first provider and second in the normal chain. |
| Ollama fallback | `https://ollama.com/v1/chat/completions`, `OLLAMA_API_KEY`, model `gpt-oss:120b`; accepts both OpenAI-style and native Ollama response shapes. |
| Groq integration | `https://api.groq.com/openai/v1/chat/completions`, `GROQ_API_KEY`, JSON mode, 30 s timeout; plus a **file lock** (`<tempdir>/mios_groq.lock`) serializing Groq calls and a **429 retry loop (max 3)** that parses "try again in Xs" (capped at 5 s sleep). |
| Gemini | Used only if groq/opencode/ollama are circuit-broken or fail; thinking-token handling for gemini-3.x (`thinkingLevel: LOW`) and gemini-2.5.x (`thinkingBudget: 0`). |
| Provider locking | **Committee-level**: `AdversarialCommittee.deliberate` iterates the provider chain and locks an **entire voting cycle to one provider** (`force_provider`). If any AI member abstains (`provider == "fallback"`), the whole committee re-votes on the next provider. |
| Circuit breaker | Per provider (not per model), 600 s auto-reset TTL (`_CIRCUIT_RESET_SECONDS`). |
| Retry behavior | Retryable statuses `{429, 500, 502, 503, 504, timeout, invalid_json, schema_invalid}` → try next model of same provider. Any other status (401/403/unlisted 4xx, missing key) is permanent → skip remaining models, next provider. |
| Rate-limit handling | Groq 429 backoff loop + serialization lock; other providers rely on chain fallback. Data-provider `retry_attempts` config is **not implemented** (see J). |
| Deterministic fallback | On `AIProviderError`: `_fallback_committee` → `WAIT`, confidence capped at `fallback_confidence_cap` (35), `confidence_adjustment` −8. Specialist reports are always deterministic (no per-specialist LLM calls). |
| Schema validation | `AIJsonValidator` (pydantic); committee votes validated against `_MemberVotePayload` both as a streaming `is_valid` gate and after completion. |
| Token guard | Inside `LLMJsonClient.complete`: **`SAFE_INPUT_BUDGET = 6500`**, hard ceiling `MAX_INPUT_TOKENS = 8000`; truncates user prompt with `[TRUNCATED_BY_GLOBAL_GUARD]`. Context builder budgets 7000; committee re-compresses per member. |

---

## E. Current Decision Flow (exact transition points)

```
Market data          → RepositoryBackedMarketDataCollector.collect()      [orchestrator.py:117]
Deterministic engines→ technical/fundamental/institutional/news/
                       geopolitical/regime + PullbackRiskEngine           [orchestrator.py:132-160]
                       (pullback evidence appended to technical.evidence) [orchestrator.py:159-160]
Analysis bundle      → AnalysisBundle(...)                                [orchestrator.py:162-170]
AI research desk     → AIResearchDesk.analyze (deterministic specialists
                       + AdversarialCommittee LLM votes)                  [orchestrator.py:171-173]
(second pass)        → news/geopolitical engines re-run only if a real AI
                       specialist report exists                           [orchestrator.py:174-213]
Opportunity score    → OpportunityFilter.assess (GLOBAL gates)            [orchestrator.py:215]
Investment score     → InvestmentScoringEngine.score (regime weights)     [orchestrator.py:216]
Confidence           → DecisionEngine decision trace: base avg →
                       bounded Bayesian alignment update → contradiction
                       (−3 each, cap 20) → missing evidence (−4 each,
                       cap 20) → committee adjustment (bounded −15..+10)  [decision_engine.py:178-282]
Unified decision     → DecisionEngine.decide → UnifiedDecisionBuilder     [orchestrator.py:229-235]
ModeExecutionPolicy  → policy.evaluate per mode (physical/forex/etf)      [orchestrator.py:267-317]
Adapters             → Physical/Forex/ETF adapters                        [orchestrator.py:280-301]
Final CLI output     → main._print_mode_output (--mode flag)              [main.py:366-477]
```

### Gates

| Gate | Scope | Value |
|---|---|---|
| `minimum_confidence_for_action` | **Global** (OpportunityFilter + DecisionEngine) | 60 |
| `max_high_severity_risks_for_action` | **Global** | 1 |
| Universal HIGH/CRITICAL safety | **Universal** — `ModeExecutionPolicy` returns non-actionable for any mode if any risk severity is HIGH or CRITICAL; NEUTRAL bias can never be upgraded | applies to all modes |
| Physical confidence threshold | Mode-specific | **85** |
| Physical opportunity / investment minimums | Mode-specific | **75 / 70** |
| Physical minimum expected move | Mode-specific | **$50** |
| Forex confidence threshold | Mode-specific | **60** (60–70 additionally requires technical-bias alignment + expected move > 0; ≥ `forex_high_confidence_threshold` = **70** passes unconditionally) |
| Forex opportunity / investment minimums | Mode-specific | **60 / 60** |
| Forex minimum expected move | Mode-specific | **$10** |
| ETF confidence threshold | Mode-specific | **70**, plus macro + institutional biases must not oppose (NEUTRAL allowed) |
| ETF opportunity / investment minimums | Mode-specific | **70 / 65** |
| ETF minimum expected move | Mode-specific | **$40** |
| Expected-move gate order | Per mode, checked before confidence in `ModeExecutionPolicy` | — |

**Verified:** opportunity/investment *minimums* and expected-move minimums are mode-specific; only the base confidence-for-action and high-risk-count gates are global. HIGH/CRITICAL blocking is universal.

---

## F. Pullback Risk Status

| Item | Current state (`app/application/engines/pullback_risk_engine.py`) |
|---|---|
| Score range | 0–100 (clamped). |
| Components / weights | RSI(14) ≥ 70 exhaustion (max 20) + resistance/bearish-FVG proximity (max 20) + momentum deterioration (max 15) + >5% extension above EMA(200) (max 10) + trend quality < 40 (max 10) + liquidity sweep (max 10) + RANGE/HIGH_VOLATILITY regime (max 10) + ATR% > 1% (max 5). |
| Buckets | `<30 LOW`, `30–59 MEDIUM`, `60–79 HIGH`, `≥80 EXTREME`. |
| Entry into evidence | `report_to_evidence()` converts report + drivers into `EvidenceRecord`s (strength LOW→CRITICAL by level) appended to `technical.evidence` (orchestrator.py:159–160). Report itself attached as `DecisionReport.pullback_risk_report`. |
| Committee visibility | Yes — evidence flows through `AIContextBuilder._rank_evidence` into the committee prompt, and the report is displayed in CLI/dashboard. |
| Effect on final action | **Indirect only.** No gate in `OpportunityFilter` or `ModeExecutionPolicy` reads the pullback score; it cannot force WAIT on its own. |
| Informational-only status | **CONFIRMED** — consistent with `docs/PULLBACK_CALIBRATION_FINAL.md` ("Final Decision: RISK SCORE ONLY"). ⚠ Caveat: an EXTREME score emits CRITICAL-strength evidence, which *could* enter the buggy escalation check in `research_desk.py` (see J.4). The pullback engine itself remains informational. |

---

## G. Technical Engine Status

| Capability | Present? | Implementation |
|---|---|---|
| RSI(14) | ✅ | `technical_features.py::_rsi` (Wilder smoothing) — computed on **daily closes**; surfaced as evidence `TECH-RSI-001` and used by PullbackRiskEngine. |
| EMA(200) | ✅ | `technical_features.py::_ema` on daily closes; needs ≥200 daily candles, else `None`; evidence `TECH-EMA200-001`. |
| Daily timeframe | ✅ | `daily_bars` filter (`Timeframe.ONE_DAY`) + `_trend_bias` → `daily_trend`; evidence `TECH-DAILY-TREND-001`. Note: production collection fetches H1 bars (orchestrator fallback / backtest fetches 1H); daily features only populate when daily bars are present in the snapshot. |
| ATR | ✅ (approximate) | `technical_features.py` line 34: mean of `high − low` over last **14 primary-timeframe bars** — **not true range** (ignores gaps). |
| Multi-timeframe | ✅ | `_timeframe_biases`, `_multi_timeframe_aligned`, `_higher_timeframe_confirmed` (H1↔H4); evidence `TECH-MTF-001`, `TECH-HTF-001`. |
| SMC / FVG | ✅ | `_detect_fair_value_gaps`, `_detect_order_block`, `_detect_breaker_block`, `_detect_mitigation_block`, `_detect_structure_signal` (BOS/CHoCH). |
| Liquidity sweeps | ✅ | `_detect_liquidity_sweep` (swing-high/low stop runs with reclaim close). |
| Trend quality | ✅ | `_trend_quality` (MA spread normalized by ATR + MTF alignment bonus). |
| Support/resistance | ✅ | 20-bar min/max + `_level_confidence` (touch counting); feeds `SupportResistanceLevels` and invalidation conditions. |
| Extras | ✅ | Premium/discount zones, Asian range, VWAP, volume ratio/confirmation, volatility regime. |

---

## H. Expected Move Status

| Item | Current state |
|---|---|
| Formula | `expected_move = max(ATR × 2, Decimal("1"))` — `technical_engine.py` line 53. |
| ATR source | Mean of `high − low` (range, not true range) over the last **14** bars. |
| Timeframe / bars | Primary timeframe = **H1** when present (else whatever bars exist); **14 bars**. |
| Floor | **$1** (also `min_usd=None` if the value is 0). `max_usd = min_usd × 1.5`. |
| Direction | From recommendation (BUY→UP, TAKE_PROFIT/STRONG_SELL→DOWN), else technical bias, else SIDEWAYS. |
| Display | `DecisionReport.expected_move`; CLI always prints it (WAIT and actionable) in `main.py` and `ModePolicyPresentation.expected_move`; dashboard cards. |
| Mode differences | Formula is **identical for all modes**; modes only differ in minimum gates ($50 physical / $10 forex / $40 ETF) enforced by `ModeExecutionPolicy`. |
| Closed market / flat candles | No explicit session/closed-market handling. Protections: (1) stale-candle risk if latest bar older than `stale_candle_threshold_minutes` (120) → MEDIUM risk; (2) flat candles → tiny ATR → $1 floor → fails physical/ETF move gates → WAIT; (3) <5 candles → `NO_DATA` technical status with CRITICAL risk, which blocks action via risk gates. |

---

## I. Adapter Consistency

| Check | Verdict |
|---|---|
| Physical WAIT → conservative allocation | ✅ `action="WAIT"`, allocation "Maintain current allocation; wait for stronger confirmation." |
| ETF WAIT → conservative allocation | ✅ Same pattern ("Maintain current ETF allocation; wait for stronger confirmation."). |
| Forex WAIT → no contradictory trade params | ⚠ **Partially.** Presentation layer suppresses entry/TP/SL when `is_wait` (orchestrator `mode_results` and CLI), but `ForexAdapter.adapt` itself takes **no `is_actionable` flag**: the returned `ForexDecision` still contains `signal=LONG/SHORT`, `entry`, `take_profit`, `stop_loss` whenever the unified bias is directional, even when policy said WAIT. Any consumer reading the raw adapter output (rather than the filtered presentation) sees contradictory trade parameters. |
| Actionable → TP/SL behavior | ⚠ TP/SL are **fixed percentages** (target +4%, stop −2%; 2:1 R:R) independent of the expected move / ATR. Consistent, but not volatility-aware. |
| LONG vs SHORT support | ✅ Both directions implemented symmetrically (forex), and bearish alignment maps to TAKE_PROFIT/STRONG_SELL through the unified bias. |
| Expected Move display | ✅ Always displayed (WAIT and actionable) in CLI and mode presentation. |
| Contradictions found | (1) Forex raw adapter output during WAIT (above). (2) `_print_mode_output` recomputes policy and formatting independently of the orchestrator's already-computed `mode_policy_results` — duplicated logic that can drift. |

---

## J. Integrity Risks

1. **No git repository.** Zero change history or safety net for the canonical hackathon codebase.
2. **Backup files inside source:** `app/presentation/dashboard.py.backup`, `.bak`, `.bak2`, `.v3.bak`, `.v3-final-backup` (~180 KB total).
3. **Scratch/generated clutter:** `scratch.py`, `scratch_js.js`, root-level 0-byte `mios.db`, `latest.json`, `data/e2e_test.db`, `data/e2e_rss.db`, orphaned `data/e2e_keyed.db-shm/-wal`, `.pytest_tmp/` (27 dirs), `CHANGES_MERGE_2026-07-30.md` merge artifact.
4. **Latent crash — escalation check:** `AIResearchDesk._evaluate_escalation` reads `ev.direction.value` on `EvidenceRecord` objects, but `EvidenceRecord` (`app/domain/common.py`) has **no `direction` field**. If any technical/fundamental/institutional evidence has CRITICAL strength (e.g. technical `NO_DATA` evidence, or an EXTREME pullback evidence record), this raises an unhandled `AttributeError` — the surrounding `except` only catches `AIProviderError`. The 231 tests do not exercise this path.
5. **Duplicated config field:** `AIResearchConfig.escalation` declared twice (`app/application/ai_research_config.py` lines 34–35).
6. **Stale docstring:** `app/ai/committee.py` module docstring claims strategist/tactical are Gemini-pinned; code pins **all three AI members to groq**.
7. **Dead config fields:** global `minimum_expected_move_usd` (never read — only per-mode variants are used); provider `retry_attempts` (no retry loop exists in `ProviderBase`); `AIContextBuilder.hard_limit` (unused).
8. **Bare `except:`** in `app/benchmark/scoring.py` line 33.
9. **Config duplication:** orchestrator re-loads `config/decision_engine.json` from disk with a hardcoded relative path on **every** `run_once` (orchestrator.py:237–240) although an identical config is already injected via constructor.
10. **Duplicated formatting logic:** expected-move string formatting appears in both `main._print_mode_output` and `orchestrator.run_once`.
11. **`.env.example` mismatches:** lists `OPENROUTER_API_KEY` (no OpenRouter provider exists in code) and omits `TWELVE_DATA_API_KEY`, `FRED_API_KEY`, `NEWSAPI_KEY`, `FINNHUB_API_KEY`, `DISCORD_WEBHOOK_URL` which `platform.json` references.
12. **Budget inconsistency:** context builder targets 7000 tokens while the global guard truncates at 6500 — functional but layered guard rails rather than one source of truth.
13. **`OpportunityFilter.required_action`** hardcoded to `BUY` on pass (cosmetic; consumers use `passed` + scores).
14. **Groq lock file fragility:** OS-temp-dir lock (`mios_groq.lock`) with busy-wait; a crashed process can leave the lock and stall subsequent cycles (removed in `finally`, but not on hard kill).
15. No dead test files detected — all 231 tests pass; provider names are consistent (`deterministic_fallback` string contract deliberately preserved, documented in `research_desk.py`).

---

## K. Documentation / Experiment Status

| Classification | Artifacts |
|---|---|
| **CANONICAL** | `docs/FINAL_ARCHITECTURE.md`, `docs/CONFIGURATION.md`, `docs/DASHBOARD_DESIGN_SPEC.md`, `docs/DATABASE_ROADMAP.md`, `docs/MIOS_DASHBOARD_MOCKUP.png`, `README.md`, `contracts/schemas/*`, `docs/PULLBACK_CALIBRATION_FINAL.md` (records the standing "risk score only" policy). |
| **EXPERIMENTAL** | `app/benchmark/` + `scripts/benchmark_committee.py` + `data/benchmark_scenarios/` (12 scenarios), `data/benchmark_results/` (leaderboards v1/v2.1, pilot + raw results incl. many model variants), `scripts/generate_scenarios.py`. |
| **HISTORICAL** | `docs/PRE_FREEZE_FORENSIC_AUDIT.md`, `docs/MODE_GATE_FORENSIC_AUDIT.md`, `docs/JOURNAL_DESERIALIZATION_FORENSIC_AUDIT.md`, `docs/AI_PROVIDER_FORENSIC_DIAGNOSIS.md`, `docs/MERGE_DEPRECATION_AUDIT.md`, `CHANGES_MERGE_2026-07-30.md`, `docs/PULLBACK_CALIBRATION_REPORT.md`, `docs/PULLBACK_VALIDATION_REPORT.md`. |
| **GENERATED** | `latest.json`, `data/decision_journal.json`, `data/mios.db*`, `data/paper_trading.json`, `data/gdelt_cooldown.json`, `logs/mios.log`, `__pycache__/`, `.pytest_cache/`, `.pytest_tmp/`, benchmark `raw/` outputs. |
| **POSSIBLY STALE** | The 5 `dashboard.py.*` backup files, `scratch.py`, `scratch_js.js`, root-level empty `mios.db`, `data/e2e_*.db` + orphaned `-shm/-wal` files, `.env.example` OpenRouter entry. |
| Calibration scripts | `scripts/calibrate_pullback_risk.py`, `scripts/validate_pullback_risk.py`, `scripts/advanced_calibration.py` — used to produce `data/pullback_validation/*`; conclusions already captured in docs, scripts kept for reproducibility. |

---

## L. Hackathon Readiness

| Category | Rating | Why |
|---|---|---|
| Architecture | 🟢 GREEN | Clean layered structure (domain/application/infrastructure/AI), single orchestrator, contracts + JSON schemas, consistent ports/adapters. |
| Deterministic intelligence | 🟢 GREEN | Full indicator suite (RSI/EMA/ATR/SMC/FVG/sweeps/MTF/trend quality/S&R), 6 engines + regime classification, all test-covered. |
| AI committee | 🟡 YELLOW | Working adversarial 4-member weighted committee with deterministic fallback, but stale docstring, all-AI-members-on-Groq pinning, and the latent escalation `AttributeError`. |
| Provider reliability | 🟡 YELLOW | Strong chain fallback + circuit breakers + token guard + Groq rate-limit handling; however data-provider `retry_attempts` is unimplemented and the Groq lock file is fragile. |
| Risk controls | 🟢 GREEN | Universal HIGH/CRITICAL blocking, WAIT-priority discipline filter, bounded committee influence (−15..+10), NEUTRAL never upgraded. |
| Mode execution | 🟢 GREEN | Mode-specific confidence/opportunity/investment/expected-move gates, correct WAIT semantics in physical/ETF presentation. |
| Pullback intelligence | 🟢 GREEN | Verified informational-only per calibration decision; visible to committee and CLI without gating power. |
| Testing | 🟢 GREEN | 231/231 passing in ~44 s; gaps only in the untested CRITICAL-evidence escalation path. |
| Documentation | 🟡 YELLOW | Good canonical docs + thorough audit trail, but heavy historical clutter and stale committee docstring. |
| Demo readiness | 🟡 YELLOW | `run-once --mode` path works end-to-end with expected-move display; risks: **no git safety net**, backup/scratch clutter, potential crash if CRITICAL evidence appears mid-demo (J.4). |

### Recommended next actions (not performed — read-only audit)

1. **Initialize a git repository and commit the current state immediately** (highest priority — zero recovery capability today).
2. Fix the `_evaluate_escalation` `EvidenceRecord.direction` access (latent crash on CRITICAL evidence paths).
3. Delete the 5 dashboard backup files, scratch files, root empty `mios.db`, and `data/e2e_*.db` artifacts.
4. Reconcile `committee.py` docstring with the actual Groq pinning, remove the duplicated `escalation` field, and extend `.env.example` to match `platform.json` key names.
5. Either implement provider retry or remove the `retry_attempts` config claim; unify the 7000/6500 token budgets.
6. Decide whether raw `ForexDecision` should suppress TP/SL during WAIT or rely solely on presentation filtering.

---

**NO SOURCE MODIFICATIONS MADE.** The only file created during this audit is this report: `docs/CURRENT_STATE_AUDIT.md`. No source, test, config, or data file was modified, renamed, or deleted.
