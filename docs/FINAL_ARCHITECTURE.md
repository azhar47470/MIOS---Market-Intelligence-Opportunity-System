# MIOS v5.0 Final Architecture

The architecture below represents the final stable build of the Market Intelligence Operating System (MIOS) used for the hackathon release. It reflects the merger of the rigorous intelligence engines with the scalable ingestion pipelines and multi-modal presentation adapters.

`	ext
                DATA INGESTION (15 sources: Reuters, Fed, ECB, BIS, LBMA, etc.)
                     |
          EVENT / NARRATIVE PIPELINE (Deduplication, Event Extraction)
                     |
              VERIFICATION (Cross-Source Corroboration)
                     |
               EVIDENCE (MarketDataSnapshot)
                     |
          PROBABILISTIC REGIME (MarketRegimeEngine)
                     |
          5 SPECIALIZED ENGINES (Technical, Fundamental, Institutional, News, Geopolitical)
                     |
            DYNAMIC WEIGHTING (InvestmentScoringEngine)
                     |
          DETERMINISTIC BASELINE (OpportunityFilter)
                     |
             AI RESEARCH DESK (Adversarial Setup)
                     |
        CONDITIONAL ADVERSARIAL DEBATE (Strategist, Trader, Contrarian)
                     |
          BAYESIAN DECISION ENGINE (Conflict Penalties & Stability)
                     |
             UNIFIED DECISION (Canonical Outlook)
                     |
        +------------+------------+
        |            |            |
      FOREX       PHYSICAL       ETF
   (Entry/SL/TP) (Allocation)  (Flows)
`

## Subsystem Details

### 1. Ingestion Pipeline
Uses 15 configurable connectors integrated via \ss_news_provider\ and \
ews_connector_provider\ to fetch real-time unstructured articles and structured macro/financial data.

### 2. Events & Narratives
The \EventNarrativePipeline\ transforms 1,200+ daily articles into a dense, deduplicated graph of confirmed events and broader market narratives, stripping out noise and retaining only high-value signals.

### 3. The 5 Deterministic Engines
- **Technical**: Multi-timeframe trend, momentum, support/resistance.
- **Fundamental**: DXY correlations, economic calendar impact, Fed policy.
- **Institutional**: ETF flows, COT positioning, smart-money tracking.
- **News/Macro**: High-severity sentiment extraction.
- **Geopolitical**: Real-time conflict extraction and duration mapping.

### 4. Committee & Debate
The \AdversarialCommittee\ executes an LLM debate across specialized personas:
- **Macro Strategist** (Gemini)
- **Tactical Trader** (Gemini)
- **Contrarian** (Groq)
Each persona receives the same deterministic facts but applies different criteria to their voting. If consensus is fragmented, the Bayesian resolver steps in.

### 5. Unified Output Modes
Instead of emitting raw scores or hard-coded signal types, MIOS outputs a \UnifiedDecision\. Adapters intercept this and cast it into:
- **Physical Gold Mode**: Guidance for accumulators on allocation sizes.
- **Forex Mode**: Trade setups with explicit invalidation stops (SL/TP).
- **ETF Mode**: Outlook for GLD/IAU flows and positioning.
