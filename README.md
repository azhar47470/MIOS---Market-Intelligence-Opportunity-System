# Market Intelligence Operating System (MIOS) - v5.0 (Hackathon Release)

**MIOS is an institutional-grade, multi-engine AI intelligence platform for physical gold, forex, and ETF investors.**

Unlike traditional trading bots that generate frequent buy/sell signals, MIOS acts as a disciplined **AI Research Committee**, synthesizing a dozen market data feeds, reading 1200+ news articles via a 15-connector ingestion pipeline, parsing geopolitical conflict, and applying a rigorous Bayesian debate protocol to arrive at a stable, explainable decision.

## 🚀 Hackathon Features
- **15-Connector Pipeline**: Ingests real-time feeds from Reuters, Fed, ECB, IMF, BIS, LBMA, CFTC, and more.
- **Event & Narrative Extraction**: Deduplicates 1,200+ articles into dense clustered market narratives.
- **5 Deterministic Domain Engines**: Technical, Fundamental, Institutional, News, Geopolitical + Probabilistic Regime.
- **Conditional AI Debate**: An `AdversarialCommittee` (Macro Strategist, Tactical Trader, Contrarian) debates the evidence to challenge consensus.
- **Decision Stability & Filters**: Overrides impulsive AI recommendations using deterministic escalation logic and Bayesian resolution.
- **Unified Decision Adapters**: Presents the same canonical outlook differently for Forex (Entry/SL/TP), Physical Gold (Allocation guidance), and ETFs (Flows).

## 💻 How to Run (Demo)

Install dependencies:
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Set up your API keys in `.env` (copy from `.env.example`).

### 1. Run an Intelligence Cycle (Live)
Run MIOS and view the **Physical Gold** mode presentation:
```powershell
python -m app.main run-once --mode physical
```

View the **Forex** mode presentation:
```powershell
python -m app.main run-once --mode forex
```

View the **ETF** mode presentation:
```powershell
python -m app.main run-once --mode etf
```

### 2. View the Live Dashboard
```powershell
python -m app.main serve
```
Open `http://127.0.0.1:8765`

### 3. Run Historical Backtesting
```powershell
python -m app.main backtest --lookback 60 --horizon 5
```

## 🏗️ Architecture
See `docs/FINAL_ARCHITECTURE.md` for the complete system topology.

## 🛡️ Safety & Philosophy
If the AI Committee and deterministic filters disagree, MIOS defaults to **WAIT**. It is optimized for high-probability precision, not high-frequency trading.
