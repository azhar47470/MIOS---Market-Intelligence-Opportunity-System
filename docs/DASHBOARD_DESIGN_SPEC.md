# MIOS Hackathon Dashboard — Design Specification

> **Version:** 1.0 · **Date:** 2026-08-25 · **Status:** DESIGN REVIEW
> **Backend:** Feature-frozen. No intelligence, decision, or provider logic changes permitted.

---

## 1. Design Philosophy

This is a **quantitative market-intelligence terminal**, not a generic admin panel.

### Core Principles
1. **Intelligence Hierarchy** — The pipeline flows top-to-bottom: raw data → verified evidence → deterministic engines → AI committee → mode policy → final action. The UI must make this pipeline *legible at a glance*.
2. **Decision, Not Decoration** — Every pixel serves the decision. No gratuitous animations, gradients, or ornamental elements. Motion is used only where it conveys state change (a new decision arriving, a score transitioning).
3. **Dense But Not Crowded** — Professional terminals (Bloomberg, Refinitiv) achieve high information density through typographic hierarchy and spatial rhythm, not by shrinking fonts. We follow that approach.
4. **Same Intelligence, Three Lenses** — The single most important UX concept is that Physical, Forex, and ETF see the *identical* market intelligence but arrive at different final actions because of their execution policies. The dashboard makes this visible with a mode-switcher that changes only the bottom "Action Layer" while the shared intelligence remains constant above.
5. **Honest Uncertainty** — Scores are scores, not probabilities. Pullback Risk is `26/100`, not `26%`. Confidence attributions show penalties. Contradicting evidence is displayed alongside supporting evidence.

### Visual Identity
- **Dark financial terminal** aesthetic (near-black backgrounds, muted borders, high-contrast data)
- **Gold accent** (`#D5AD4C`) — reserved exclusively for the asset under analysis (XAU/USD) and the brand
- **Monospaced numerics** throughout for prices, scores, and percentages — tabular alignment is essential
- Typography-driven hierarchy: weight, size, and color do the work; decorative borders do not

---

## 2. Information Hierarchy

The dashboard information flows in four tiers of descending urgency:

```
TIER 1 — DECISION SUMMARY (always visible)
┌─────────────────────────────────────────────────────────────────┐
│  Gold Price  │  Final Action  │  Confidence  │  Pullback Risk  │
│  Committee   │  Expected Move │  Regime      │  Bias           │
└─────────────────────────────────────────────────────────────────┘

TIER 2 — MODE POLICY COMPARISON
┌─────────────────────────────────────────────────────────────────┐
│     PHYSICAL         │      FOREX          │      ETF          │
│  Action: WAIT        │  Action: BUY        │  Action: WAIT     │
│  Reason: Exp < $50   │  TP/SL: 4832/4640   │  Reason: Exp < $40│
│  Allocation: Hold    │  Risk: Low          │  Allocation: Hold │
└─────────────────────────────────────────────────────────────────┘

TIER 3 — ENGINE INTELLIGENCE (expandable)
┌──────────┬──────────┬───────────┬──────┬──────────┬─────────────┐
│Technical │Fundamental│Institutional│News│Geopolitical│Market Regime│
│  72/100  │  65/100   │  58/100   │45/100│  70/100  │  BULL       │
└──────────┴──────────┴───────────┴──────┴──────────┴─────────────┘

TIER 4 — EVIDENCE, TRACE & COMMITTEE MINUTES (deep-dive)
Supporting evidence, contradicting evidence, risk records,
confidence attribution waterfall, analyst reports, committee votes
```

---

## 3. Full Page Layouts

### 3.1 `/dashboard` — Command Center

The primary view. Fits on a single 1440px screen without scrolling for core data.

```
┌──────────────────────────────────────────────────────────────────────┐
│ HEADER BAR                                                          │
│ [MIOS] Gold Intelligence Terminal    XAU/USD $4,608.00   ▲ +0.42%  │
│                                      Last cycle: 2m ago   ● HEALTHY │
└──────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────┬─────────────────────────────────────┐
│                                │                                     │
│  DECISION CARD                 │  PIPELINE STATUS                    │
│  ┌────────────────────────┐    │  ┌─────────────────────────────┐    │
│  │ Committee: STRONG_BUY  │    │  │ 15 Sources → 8 Events       │    │
│  │ Conf 79% → Post 96%   │    │  │ → 12 Evidence → 6 Engines   │    │
│  │ Bias: BULLISH          │    │  │ → Pullback 26 → Committee   │    │
│  │ Pullback: LOW 26/100   │    │  │ → Mode Policy → Action      │    │
│  │ Expected: +$38.10      │    │  └─────────────────────────────┘    │
│  │ Regime: BULL            │    │                                     │
│  └────────────────────────┘    │  ENGINE SCORES (6 horizontal bars)  │
│                                │  Technical ████████░░ 72            │
│                                │  Fundamental ██████░░░ 65           │
│                                │  Institutional █████░░░ 58          │
│                                │  News ████░░░░░░ 45                 │
│                                │  Geopolitical ███████░░ 70          │
│                                │  Regime ████████░░ 80               │
│                                │                                     │
├────────────────────────────────┴─────────────────────────────────────┤
│ MODE EXECUTION COMPARISON                                            │
│ ┌──────────────────┬──────────────────┬──────────────────┐           │
│ │ ● PHYSICAL       │ ● FOREX          │ ● ETF            │           │
│ │                  │                  │                  │           │
│ │ Action: WAIT     │ Signal: LONG     │ Action: WAIT     │           │
│ │ Reason: Exp Move │ Entry: $4,608    │ Reason: Exp Move │           │
│ │   $38 < $50 min  │ TP: $4,792      │   $38 < $40 min  │           │
│ │ Alloc: Maintain  │ SL: $4,516      │ Alloc: Maintain  │           │
│ │ Conviction: Med  │ Risk: Low       │ Vehicle: GLD/IAU │           │
│ │ Horizon: 2-4 wks │ Horizon: 1-2 wk │ Horizon: 2-4 wks│           │
│ └──────────────────┴──────────────────┴──────────────────┘           │
├──────────────────────────────────────────────────────────────────────┤
│ PULLBACK RISK │ CONFIDENCE WATERFALL │ KEY RISKS                     │
│ Score: 26/100 │ Base: 79%            │ · Fed policy uncertainty (H)  │
│ Level: LOW    │ + Evidence: +8       │ · Technical exhaustion (M)    │
│ RSI: 11pts    │ - Contradiction: -3  │ · DXY reversal risk (M)      │
│ Momentum: 5   │ - Missing: -2        │                               │
│ Trend: 10     │ + Committee: +14     │                               │
│               │ = Posterior: 96%      │                               │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 `/intelligence` — Deep Engine Dive

Expandable engine cards with full evidence, each engine gets a dedicated section.

```
┌──────────────────────────────────────────────────────────────────────┐
│ HEADER BAR                                                          │
├──────────────────────────────────────────────────────────────────────┤
│ [TAB BAR] Technical | Fundamental | Institutional | News | Geo | Regime │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  TECHNICAL ENGINE (example expanded state)                           │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐      │
│  │ Score: 72    │ Trend: 68    │ Momentum: 45 │ Volatility:55│      │
│  └──────────────┴──────────────┴──────────────┴──────────────┘      │
│                                                                      │
│  ┌─────────────────────────────┬────────────────────────────────┐    │
│  │ Supporting Evidence         │ Contradicting Evidence          │    │
│  │ · RSI(14) = 75.70 overbought│ · Momentum flat                │    │
│  │ · EMA(200) trend confirmed  │ · Weak trend quality           │    │
│  │ · MTF aligned bullish       │                                │    │
│  └─────────────────────────────┴────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────┬────────────────────────────────┐    │
│  │ Support/Resistance Levels   │ Market Structure                │    │
│  │ R3: $4,720                  │ Structure: BULLISH              │    │
│  │ R2: $4,680                  │ Asian Range: Break Above        │    │
│  │ R1: $4,650                  │ FVGs: 2 unfilled                │    │
│  │ ─ Current: $4,608 ─        │ Order Block: Bullish @ $4,580   │    │
│  │ S1: $4,580                  │ Liquidity Sweep: None           │    │
│  │ S2: $4,540                  │ Premium/Discount: PREMIUM       │    │
│  │ S3: $4,500                  │ VWAP: $4,595                    │    │
│  └─────────────────────────────┴────────────────────────────────┘    │
│                                                                      │
│  COMMITTEE SECTION (below engine tabs)                               │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ Investment Committee: STRONG_BUY (79%)                       │    │
│  │                                                              │    │
│  │ MEMBER VOTES                                                 │    │
│  │ ┌──────────┬────────┬──────┬────────┬─────────────────────┐  │    │
│  │ │ Member   │ Direction│Conf │ Weight │ Key Reasoning       │  │    │
│  │ ├──────────┼────────┼──────┼────────┼─────────────────────┤  │    │
│  │ │ Macro    │ LONG   │ 0.82 │ 0.25  │ Rate cut cycle...   │  │    │
│  │ │ Technical│ LONG   │ 0.78 │ 0.20  │ Trend confirmed...  │  │    │
│  │ │ Risk     │ WAIT   │ 0.65 │ 0.15  │ RSI overbought...   │  │    │
│  │ │ Devil's  │ SHORT  │ 0.45 │ 0.10  │ DXY reversal...     │  │    │
│  │ └──────────┴────────┴──────┴────────┴─────────────────────┘  │    │
│  │                                                              │    │
│  │ Disagreements:                                               │    │
│  │ · Risk analyst flags RSI exhaustion vs macro strength        │    │
│  │ · Devil's advocate challenges duration of rate cut thesis    │    │
│  │                                                              │    │
│  │ Missing Evidence: COT data delayed 3 days                    │    │
│  └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.3 `/history` — Decision Journal Timeline

```
┌──────────────────────────────────────────────────────────────────────┐
│ HEADER BAR                                                          │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  CONFIDENCE TIMELINE (sparkline-style bar chart, last 20 decisions) │
│  ░░▓▓▓█▓▓░▓█▓▓░▓▓▓█▓▓                                              │
│  Each bar colored by recommendation (gold=BUY, gray=WAIT, red=SELL) │
│                                                                      │
│  DECISION TABLE                                                      │
│  ┌──────────┬──────────┬──────┬───────┬───────┬──────┬──────────┐   │
│  │ Time     │ Recommend│ Conf │ Invest│ Regime│ Bias │ Exp Move │   │
│  ├──────────┼──────────┼──────┼───────┼───────┼──────┼──────────┤   │
│  │ 14:30 UTC│ STRONG_BUY│ 96% │ 82    │ BULL  │ BULL │ +$38.10  │   │
│  │ 10:30 UTC│ BUY      │ 88% │ 75    │ BULL  │ BULL │ +$42.50  │   │
│  │ 06:30 UTC│ HOLD     │ 72% │ 60    │ RANGE │ NEUT │ +$12.00  │   │
│  └──────────┴──────────┴──────┴───────┴───────┴──────┴──────────┘   │
│                                                                      │
│  Click any row to expand: full evidence, committee minutes, trace   │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.4 `/demo` — 3-Minute Hackathon Walkthrough

A guided, auto-scrolling view designed for live presentation:

```
STEP 1: "15 Data Sources" — animated pipeline visualization
STEP 2: "Intelligence Engines" — engine scores fan out
STEP 3: "AI Committee Deliberation" — votes appear one by one
STEP 4: "Same Intelligence, Three Actions" — mode cards appear
STEP 5: "Pullback Risk Engine" — score breakdown appears
STEP 6: "Decision Trace" — confidence waterfall animates
```

---

## 4. Component Tree

```
App
├── Layout
│   ├── HeaderBar
│   │   ├── BrandMark ("MIOS")
│   │   ├── AssetTicker (XAU/USD price + change)
│   │   ├── CycleTimestamp
│   │   └── SystemHealthBadge
│   ├── NavigationRail
│   │   └── NavItem[] (/dashboard, /intelligence, /history, /demo)
│   └── MainContent
│
├── Pages
│   ├── DashboardPage
│   │   ├── DecisionCard
│   │   │   ├── CommitteeOpinionBadge
│   │   │   ├── ConfidenceGauge (base → posterior)
│   │   │   ├── DirectionalBiasIndicator
│   │   │   ├── PullbackRiskMeter
│   │   │   ├── ExpectedMoveDisplay
│   │   │   └── RegimeBadge
│   │   ├── PipelineFlow (horizontal step visualization)
│   │   ├── EngineScoreStrip (6 horizontal bar gauges)
│   │   ├── ModeComparisonPanel
│   │   │   ├── PhysicalModeCard
│   │   │   ├── ForexModeCard
│   │   │   └── ETFModeCard
│   │   ├── PullbackBreakdownPanel
│   │   ├── ConfidenceWaterfallChart
│   │   └── RiskSummaryList
│   │
│   ├── IntelligencePage
│   │   ├── EngineTabBar
│   │   ├── EngineDetailPanel (per engine)
│   │   │   ├── ScoreKPIRow
│   │   │   ├── EvidenceSplitView (supporting | contradicting)
│   │   │   └── EngineSpecificContent
│   │   │       ├── TechnicalLevelsTable (for technical)
│   │   │       ├── MacroNarrativeBlock (for fundamental)
│   │   │       └── PositioningSummary (for institutional)
│   │   ├── CommitteePanel
│   │   │   ├── VotesTable
│   │   │   ├── DisagreementsList
│   │   │   └── MissingEvidenceList
│   │   └── ProviderTelemetryPanel
│   │       ├── ProviderStatusGrid
│   │       └── AIUsageSummary
│   │
│   ├── HistoryPage
│   │   ├── ConfidenceTimeline
│   │   ├── DecisionTable
│   │   └── DecisionExpandedRow
│   │
│   └── DemoPage
│       ├── DemoStepController
│       └── DemoSlide[] (animated pipeline steps)
│
└── Primitives
    ├── ScoreBar (horizontal fill bar with label)
    ├── KPICard (label + metric + optional delta)
    ├── Badge (colored pill: regime, bias, risk level)
    ├── EvidenceList (category-tagged list items)
    ├── DataTable (sortable, expandable rows)
    └── WaterfallChart (confidence attribution)
```

---

## 5. Design Tokens

```css
/* === SURFACES === */
--bg-base:         #0B0E11;      /* deepest background */
--bg-surface:      #12171D;      /* card/panel background */
--bg-surface-alt:  #181E26;      /* elevated card (hover, active tab) */
--bg-inset:        #0E1217;      /* inset wells, code blocks */
--border-subtle:   #242C37;      /* panel borders */
--border-muted:    #1C2430;      /* inner dividers */

/* === TEXT === */
--text-primary:    #E8EDF2;      /* headings, primary data */
--text-secondary:  #9BA5B2;      /* labels, descriptions */
--text-tertiary:   #5C6672;      /* timestamps, footnotes */
--text-inverse:    #0B0E11;      /* text on bright badges */

/* === SEMANTIC COLORS === */
--color-gold:      #D4A84B;      /* XAU brand accent, primary CTA */
--color-gold-dim:  #A88838;      /* gold at reduced emphasis */
--color-bullish:   #3FBA76;      /* bullish bias, positive moves, BUY */
--color-bearish:   #E06860;      /* bearish bias, negative moves, SELL */
--color-neutral:   #6B7685;      /* WAIT / HOLD / neutral states */
--color-warning:   #D4A032;      /* amber warnings */
--color-info:      #4A9BD9;      /* informational accents */

/* === RISK LEVELS === */
--risk-low:        #3FBA76;
--risk-medium:     #D4A032;
--risk-high:       #E06860;
--risk-extreme:    #C4384C;

/* === SPACING === */
--space-xs:        4px;
--space-sm:        8px;
--space-md:        12px;
--space-lg:        16px;
--space-xl:        24px;
--space-2xl:       32px;

/* === RADIUS === */
--radius-sm:       4px;
--radius-md:       6px;
--radius-lg:       8px;

/* === SHADOWS === */
--shadow-panel:    0 1px 3px rgba(0,0,0,0.4);
--shadow-elevated: 0 4px 12px rgba(0,0,0,0.5);
```

---

## 6. Typography

| Role | Font | Weight | Size | Line Height | Tracking |
|------|------|--------|------|-------------|----------|
| **Page Title** | Inter | 600 | 20px | 1.3 | -0.01em |
| **Section Header** | Inter | 600 | 14px | 1.4 | 0.02em (uppercase) |
| **KPI Value** | JetBrains Mono | 700 | 28px | 1.1 | -0.02em |
| **KPI Value (sm)** | JetBrains Mono | 600 | 20px | 1.2 | -0.01em |
| **Body** | Inter | 400 | 13px | 1.5 | 0 |
| **Label** | Inter | 500 | 11px | 1.3 | 0.04em (uppercase) |
| **Data Cell** | JetBrains Mono | 400 | 13px | 1.4 | 0 |
| **Caption/Timestamp** | Inter | 400 | 11px | 1.3 | 0 |
| **Badge** | Inter | 600 | 11px | 1 | 0.03em |
| **Price Ticker** | JetBrains Mono | 700 | 16px | 1.2 | -0.01em |

**Fonts loaded:**
- **Inter** (Variable, wght 400..700) — UI text
- **JetBrains Mono** (Variable, wght 400..700) — all numeric data

**Rule:** Every number that represents a score, price, percentage, or count uses `JetBrains Mono`. Every label, description, and paragraph uses `Inter`.

---

## 7. Color Semantics

| Data Element | Color Token | Example |
|---|---|---|
| Gold spot price | `--color-gold` | `$4,608.20` |
| BULLISH bias/BUY/LONG | `--color-bullish` | Green badge |
| BEARISH bias/SELL/SHORT | `--color-bearish` | Red badge |
| NEUTRAL/WAIT/HOLD | `--color-neutral` | Gray badge |
| Pullback Risk LOW | `--risk-low` | Green |
| Pullback Risk MEDIUM | `--risk-medium` | Amber |
| Pullback Risk HIGH | `--risk-high` | Red |
| Pullback Risk EXTREME | `--risk-extreme` | Deep red |
| Confidence ≥ 80% | `--color-bullish` | Green numeral |
| Confidence 60–79% | `--color-warning` | Amber numeral |
| Confidence < 60% | `--color-bearish` | Red numeral |
| Engine score bar fill | `--color-gold` | Gold bar |
| Confidence waterfall + | `--color-bullish` | Green segment |
| Confidence waterfall − | `--color-bearish` | Red segment |
| Provider SUCCESS | `--color-bullish` | Green dot |
| Provider FAILED | `--color-bearish` | Red dot |
| Provider STALE_DATA | `--color-warning` | Amber dot |

---

## 8. Chart Strategy

Only three chart types. No chart libraries beyond what raw SVG/Canvas can provide (keeps bundle tiny for hackathon).

### 8.1 Horizontal Score Bars
Used for: engine scores (6 bars), pullback component breakdown.
Implementation: CSS `width` on a `<div>` inside a track. No JS charting needed.

### 8.2 Confidence Waterfall
Used for: `DecisionTrace` attribution (base → adjustments → posterior).
Implementation: Inline SVG. Segments stack horizontally. Green for positive contributions, red for negative. Labels above each segment. Total width = posterior confidence %.

### 8.3 Confidence Timeline
Used for: `/history` sparkline showing last 20 decisions.
Implementation: Vertical bars in a CSS grid. Bar height = confidence %. Bar color = recommendation mapping (gold=BUY, green=STRONG_BUY, gray=WAIT/HOLD, red=SELL).

**No pie charts. No line charts. No animated transitions on data.** These are terminal instruments, not dashboards.

---

## 9. Responsive Behavior

| Breakpoint | Layout |
|---|---|
| **≥ 1280px** | Full 3-column mode comparison, 2-column intelligence split |
| **960–1279px** | 2-column mode comparison (ETF wraps below), sidebar collapses to top bar |
| **≤ 959px** | Single column, mode cards stack vertically, navigation becomes horizontal scroll tabs |
| **≤ 600px** | KPI grid becomes 2-column, engine bars stack, full mobile-optimized |

Navigation rail (left sidebar) collapses to a horizontal tab bar on screens < 960px.

---

## 10. API / Data Requirements

All endpoints already exist in `app/presentation/dashboard.py`. No new backend routes needed.

| Dashboard Section | API Endpoint | Data Model |
|---|---|---|
| Gold Price + Change | `GET /api/latest` | `DecisionReport.support_resistance`, spot from journal |
| Decision Card | `GET /api/latest` | `DecisionReport` (recommendation, confidence, expected_move, market_regime, pullback_risk_report) |
| Engine Scores | `GET /api/engines/{name}` (×6) | `EngineBreakdown` (score, confidence, evidence) |
| Mode Comparison | `GET /api/latest` + client-side | `UnifiedDecision` + `ModeExecutionPolicy` (evaluated client-side from thresholds, or pre-computed) |
| Committee | `GET /api/research` | `ResearchDeskReport` (analyst_reports, committee_report, committee_votes) |
| Decision Trace | `GET /api/decision-trace` | `DecisionTrace` (base, posterior, attributions) |
| Provider Status | `GET /api/provider-status` | `provider_statuses` dict |
| System Health | `GET /api/health` | Engine runtime, AI token usage |
| History | `GET /api/history` | Array of `DecisionReport` |
| Paper Trading | `GET /api/paper-trading` | Open position, closed P&L, hit rate |
| Pullback Risk | `GET /api/latest` | `DecisionReport.pullback_risk_report` |

### One Required Addition
**Mode Policy Pre-computation:** The CLI currently evaluates `ModeExecutionPolicy` at render time. For the dashboard, the orchestrator result should include the mode policy outcomes for all three modes. Two options:

**Option A (Preferred — No backend change):** Add a lightweight `/api/mode-policies` endpoint that reads the latest `DecisionReport` + `UnifiedDecision` from the journal and evaluates `ModeExecutionPolicy` for all three modes server-side. This is a pure presentation endpoint — it does not modify decision logic.

**Option B:** Include `mode_policy_results` in the orchestrator return value. This requires a minor orchestrator change (calling `ModeExecutionPolicy.evaluate()` for each mode and attaching results).

---

## 11. Hackathon 3-Minute Demo Flow

### Setup
- Dashboard running locally (`python -m app.main serve`)
- Latest live run data in decision journal
- Presenter shares screen on the `/demo` page

### Script

| Time | Step | Narration | Visual |
|---|---|---|---|
| 0:00 | **Open** | "MIOS is a real-time gold market intelligence system that synthesizes 15 live data sources into actionable decisions." | Pipeline animation: sources → events → evidence → engines |
| 0:30 | **Intelligence** | "Six deterministic engines analyze technicals, macro, institutional positioning, news, geopolitics, and market regime." | Engine score bars animate in, showing actual scores |
| 1:00 | **AI Committee** | "An AI investment committee of specialist agents deliberates and votes. Here's the latest committee: STRONG_BUY at 79% confidence." | Committee votes table appears, disagreements highlighted |
| 1:30 | **Three Modes** | "The same intelligence feeds three execution modes. Physical gold requires a $50 expected move — it says WAIT. Forex only needs $10 — it says BUY with TP/SL. ETF needs $40 — also WAIT." | Mode comparison panel highlights differences |
| 2:00 | **Pullback Risk** | "Our proprietary Pullback Risk Engine scores current market exhaustion at 26/100 — LOW. This was validated against 730 days of historical data with monotonic risk separation." | Pullback component breakdown appears |
| 2:30 | **Decision Trace** | "Every decision is fully explainable. Base confidence 79%, evidence adjustments, committee adjustments, final posterior 96%." | Waterfall chart animates |
| 2:50 | **Wrap** | "All engines, data sources, and AI providers have built-in failover. 224 tests. Ready for production." | System health panel: all green |

---

## 12. Exact Implementation Plan

### Technology Stack
- **Framework:** Vanilla HTML/CSS/JS (single-page, no build step)
- **Rationale:** The existing dashboard is already a single HTML string served from Python. We continue this approach for hackathon simplicity. No React/Vue/npm needed.
- **Fonts:** Google Fonts (Inter + JetBrains Mono) via CDN
- **Charts:** Pure CSS bars + inline SVG for waterfall
- **Data:** Fetch from existing `/api/*` endpoints with 30s auto-refresh

### Implementation Phases

#### Phase 1: Core Layout + Design System (2-3 hours)
- [ ] Replace `_dashboard_html()` in `app/presentation/dashboard.py` with new HTML
- [ ] Implement CSS design tokens, typography, and responsive grid
- [ ] Build HeaderBar with live XAU/USD ticker
- [ ] Build NavigationRail with 4 routes (dashboard, intelligence, history, demo)
- [ ] Build primitive components: KPICard, ScoreBar, Badge, EvidenceList

#### Phase 2: Dashboard Page (2-3 hours)
- [ ] DecisionCard (committee opinion, confidence, bias, pullback, expected move, regime)
- [ ] PipelineFlow visualization (horizontal step indicator)
- [ ] EngineScoreStrip (6 horizontal bars from `/api/engines/*`)
- [ ] ModeComparisonPanel (3 side-by-side cards for physical/forex/etf)
- [ ] PullbackBreakdownPanel (component-by-component score from `pullback_risk_report.drivers`)
- [ ] ConfidenceWaterfallChart (from `decision_trace`)
- [ ] RiskSummaryList

#### Phase 3: Intelligence Page (1-2 hours)
- [ ] EngineTabBar (6 tabs)
- [ ] EngineDetailPanel with evidence split view
- [ ] CommitteePanel (votes table, disagreements, missing evidence)
- [ ] ProviderTelemetryPanel (status grid + AI usage)

#### Phase 4: History + Demo Pages (1-2 hours)
- [ ] HistoryPage (confidence timeline + decision table)
- [ ] DemoPage (stepped presentation with auto-advance)

#### Phase 5: Polish + Mode Policy Endpoint (1 hour)
- [ ] Add `/api/mode-policies` endpoint (if Option A chosen)
- [ ] Responsive testing at all breakpoints
- [ ] Final color/spacing polish
- [ ] Verify all data renders from real decision journal

### Files Modified
| File | Change |
|---|---|
| `app/presentation/dashboard.py` | Replace `_dashboard_html()` with new terminal UI; add `/api/mode-policies` endpoint |

### Files NOT Modified (Feature Freeze)
- `app/application/engines/*` — No engine changes
- `app/application/execution_policy.py` — No policy changes
- `app/application/orchestrator.py` — No pipeline changes
- `app/ai/*` — No committee/LLM changes
- `app/domain/*` — No model changes
- `config/*` — No threshold changes

### Total Estimated Time: 7-11 hours
