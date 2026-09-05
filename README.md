# Market Intelligence Operating System (MIOS) — v5.0

**MIOS is an explainable, multi-engine decision-support system for gold markets — physical gold, forex, and ETF.**

MIOS is not an autonomous trading bot and does not claim to predict future prices. It behaves as a disciplined research desk: it ingests multi-source market evidence, scores it with deterministic engines, subjects it to an adversarial AI committee with strictly bounded influence, and publishes one stable, fully explained recommendation per cycle — defaulting to **WAIT** whenever evidence, confidence, or risk gates are insufficient.

## Design Principles

- **Deterministic intelligence first.** Six analysis engines and a pullback-risk engine produce every quantitative signal; AI interprets evidence but never fabricates it.
- **Multi-source evidence.** Market data, macro series, institutional positioning, and tiered news intake feed every decision.
- **Adversarial AI interpretation.** A weighted four-member committee challenges the evidence instead of rubber-stamping it.
- **Bounded AI influence.** Committee output can adjust confidence only within hard limits and can never override deterministic safety policy.
- **Provider resilience.** Four LLM providers with cycle-level locking, circuit breakers, and a fully deterministic fallback.
- **Explicit WAIT discipline.** Every mode gate failure surfaces as WAIT with a reason, never as a forced trade.
- **Testability and contracts.** Pydantic domain models, JSON-schema contracts, and a 283-test suite.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Copy `.env.example` to `.env` and supply the keys referenced by `config/platform.json` plus the news-discovery keys read directly by the RSS layer:

| Purpose | Keys |
|---|---|
| AI providers | `GROQ_API_KEY`, `OPENCODE_API_KEY`, `OLLAMA_API_KEY`, `GEMINI_API_KEY` |
| Market / macro data | `TWELVE_DATA_API_KEY`, `FRED_API_KEY` |
| News | `NEWSAPI_KEY`, `FINNHUB_API_KEY` (provider chain); `MARKETAUX_API_KEY`, `THENEWSAPI_KEY`, `WORLDNEWSAPI_KEY` (RSS discovery layer) |
| Notifications (optional) | `DISCORD_WEBHOOK_URL` |

Missing keys degrade gracefully: data layers fall back across sources, and the AI committee falls back to deterministic synthesis.

## Running MIOS

| Command | Purpose |
|---|---|
| `python -m app.main run-once --mode physical` | One intelligence cycle, physical-gold presentation |
| `python -m app.main run-once --mode forex` | One cycle, forex presentation (Entry/TP/SL when actionable) |
| `python -m app.main run-once --mode etf` | One cycle, ETF presentation |
| `python -m app.main run-once` (default `--mode json`) | Machine-readable decision report |
| `python -m app.main run-once --committee-demo` | Force a real AI committee run for demos |
| `python -m app.main run-once --notify` | Send Discord alerts when warranted |
| `python -m app.main run-forever` | Continuous monitoring (`--interval-seconds` to override) |
| `python -m app.main serve` | Live dashboard at `http://127.0.0.1:8765` |
| `python -m app.main export-dashboard` | Standalone HTML dashboard export |
| `python -m app.main backtest --lookback 60 --horizon 5` | Backtest the decision stack on recent bars |
| `python -m app.main price` | Current gold spot price |

The dashboard is served with the Python standard library (`ThreadingHTTPServer`) — no web-framework dependency.

## Architecture

### Data Layer

- **13 configured data provider endpoints**: TwelveData (XAU/USD OHLC), FRED macro series, CFTC Commitments of Traders, SPDR GLD holdings/flows, GDELT, NewsAPI, Finnhub, and four RSS/news-discovery endpoints.
- **15 tiered news connectors** (`app/infrastructure/news/`), ranked tier 1 (authoritative) to tier 5 (emergency): Reuters, Federal Reserve, ECB, IMF, BIS, US Treasury, World Gold Council, CFTC, LBMA, MarketAux, Finnhub, Google News RSS, TheNewsAPI, WorldNewsAPI, RSS Bridge.
- Cross-source verification confirms an event only when an authoritative outlet reports it and an independent source corroborates it; confirmed events become typed market narratives.

### Six Deterministic Engines

| Engine | Responsibility |
|---|---|
| Technical | RSI(14), EMA(200) on daily closes, ATR, SMC structure (BOS/CHoCH), fair-value gaps, order/breaker/mitigation blocks, liquidity sweeps, trend quality, multi-timeframe alignment |
| Fundamental | Dollar strength, rates, inflation, growth, yield-curve context from FRED series |
| Institutional | COT managed-money positioning and GLD flow interpretation |
| News | Article relevance, narrative extraction, gold-impact scoring |
| Geopolitical | Conflict and safe-haven risk parsing from news flow |
| Regime | Probabilistic regime classification (BULL / BEAR / RANGE / RISK_ON / RISK_OFF / HIGH_VOLATILITY / LOW_VOLATILITY / EVENT_DRIVEN) with dynamic engine weights |

### Pullback Risk Engine

A separate, **informational-only** structural risk gauge — not a probability and never an execution gate:

- Composite **0–100 score** from 8 weighted components: overbought RSI, resistance/FVG proximity, momentum loss, EMA200 extension, trend quality, liquidity sweeps, regime state, and volatility.
- Levels: **LOW** (<30), **MEDIUM** (30–59), **HIGH** (60–79), **EXTREME** (≥80), with the top drivers listed.
- Shown in the CLI output and dashboard and visible to the AI committee; it cannot force or block a trade by itself.

### AI Research Desk

Eight specialist reports are built **deterministically** from the engines — no per-specialist LLM calls. The only LLM traffic is the adversarial committee vote:

| Member | Weight | Role |
|---|---|---|
| Deterministic Anchor | 0.25 | Rule-based baseline grounded in engine scores |
| Macro Strategist | 0.30 | Macro and policy interpretation |
| Tactical Trader | 0.25 | Trade construction and timing |
| Contrarian Risk | 0.20 | Invalidation and reasons to wait |

The committee runs **every cycle**. What is conditional is the *depth and routing* of the AI calls:

- **Escalation triggers** — risk-elevated regimes (RISK_OFF, HIGH_VOLATILITY, EVENT_DRIVEN, UNKNOWN), low regime-stability confidence, geopolitical shock, strong engine disagreement, ambiguous technical confidence, or any CRITICAL-strength engine evidence.
- **Provider routing** — with no escalation the chain starts at **Groq** (`openai/gpt-oss-120b`); escalation re-orders it to **OpenCode/Laguna** (`laguna-s-2.1-free`) first. An entire voting cycle is locked to one provider; if a member fails, the whole committee re-votes on the next provider, falling through **Ollama** to **Gemini**.
- **Deterministic fallback** — if every provider fails, a rule-based fallback committee answers with capped confidence (35) and a negative confidence adjustment, so a cycle always completes.

### Decision Stack

```
Engine evidence
  → OpportunityFilter        (global gates: confidence ≥ 60, ≤ 1 high-severity risk)
  → InvestmentScoringEngine  (regime-weighted opportunity/investment scores)
  → DecisionEngine           (bounded Bayesian confidence update, contradiction and
                              missing-evidence penalties, committee adjustment −15…+10)
  → UnifiedDecision          (single canonical outlook)
  → ModeExecutionPolicy      (per-mode gates below)
  → Mode adapter             (Physical / Forex / ETF presentation)
```

### Expected Move

Every cycle computes an expected move as `max(ATR × 2, $1)` from the most recent 14 H1 bars. It is **always displayed**, and each mode applies its own minimum expected-move gate before any entry is presented.

### Mode Execution Policy

Per-mode gates — all must pass or the mode returns **WAIT with a reason**:

| Mode | Confidence | Opportunity | Investment | Min expected move |
|---|---|---|---|---|
| Physical | 85 | 75 | 70 | $50 |
| Forex | 60 (70 = high-confidence tier*) | 60 | 60 | $10 |
| ETF | 70 | 70 | 65 | $40 |

\* Forex confidence 60–69 additionally requires technical alignment with the bias and a positive expected move; ≥70 acts unconditionally.

When the policy returns WAIT, every adapter — including Forex — returns an explicit WAIT result with no actionable entry, take-profit, or stop-loss. Actionable forex trades carry fixed 4% take-profit / 2% stop-loss levels from the current spot.

## Safety & Philosophy

- **HIGH/CRITICAL risk blocks execution** in every mode.
- **NEUTRAL bias is never upgraded** into a trade by policy.
- **AI cannot bypass deterministic safety policy** — committee influence is bounded, and conflicting or low-confidence AI output degrades to WAIT.
- MIOS is optimized for high-probability, explainable precision — not signal frequency, and it makes no claim of guaranteed prediction accuracy.

## Testing

```powershell
python -m pytest
```

**283 passing tests** cover the engines, escalation routing, provider locking and fallback, decision flow, mode policies, adapters, ingestion, backtesting, dashboard export, and paper trading. Every inter-layer payload is validated against the JSON-schema contracts in `contracts/schemas/`.

## Configuration Map

| File | Purpose |
|---|---|
| `config/platform.json` | Data/AI providers, endpoints, polling cadence, macro series |
| `config/decision_engine.json` | Mode thresholds, engine weights, opportunity/investment gates |
| `config/ai_research.json` | Research-desk and committee configuration |
| `config/notifications.discord.json` | Discord alerting rules |
| `contracts/schemas/*.json` | JSON-schema contracts for every payload |

## Documentation

- `docs/CURRENT_STATE_AUDIT.md` — current-state forensic audit of the implementation
- `docs/FINAL_ARCHITECTURE.md` — system topology reference

---

*MIOS is a hackathon decision-support prototype and not investment advice.*
