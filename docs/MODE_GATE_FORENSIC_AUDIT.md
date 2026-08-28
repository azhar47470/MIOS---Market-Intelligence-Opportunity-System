# Mode Gate Forensic Audit

## A. Exact Formulas

**1. Opportunity Score**
Calculated by `OpportunityFilter.assess()` in `app/application/engines/decision_engine.py`.
It isolates the four "core" structural engines, explicitly excluding highly volatile news and geopolitical sentiment:
`opportunity_score = max(0, min(100, round((Technical.score + Fundamental.score + Institutional.score + Regime.score) / 4) - (len(blockers) * 15)))`

**2. Investment Score**
Calculated by `InvestmentScoringEngine.score()` in `app/application/engines/decision_engine.py`.
It is a regime-weighted average of all six engines (including News and Geopolitical):
`final_score = max(0, min(100, round(SUM(Engine.score * DynamicWeight))))`

## B. Data Flow
1. **Engine Layer**: The 6 deterministic engines calculate individual unweighted scores (0-100) and directional biases based on raw market data (e.g., an overbought RSI reduces the technical score).
2. **Quality Assessment**: `OpportunityFilter` computes the unweighted 4-engine core average. `InvestmentScoringEngine` computes the regime-weighted 6-engine average.
3. **Primary Gate (Opportunity)**: `OpportunityFilter` compares the `opportunity_score` against `thresholds.minimum_opportunity_score_for_action` (configured globally to `75`). If it fails, `passed=False` is set.
4. **Action Short-Circuit**: `DecisionEngine._recommendation()` immediately returns `Recommendation.WAIT` if `not context.opportunity.passed`.
5. **Secondary Gate (Investment)**: If the opportunity passes, `_recommendation` evaluates the `investment_score` against `minimum_investment_score_for_buy` (configured globally to `70`). If it falls between 50 and 69, it downgrades the action to `Recommendation.HOLD`.
6. **Translation**: `UnifiedDecisionBuilder` maps both `WAIT` and `HOLD` strictly to `DirectionalBias.NEUTRAL`.

## C. Meaning of Each Score
* **Posterior Confidence (98%)**: Represents **Directional Alignment**. It answers: *"How mathematically certain are we about the direction?"* If all 6 engines point UP, the Bayesian likelihood update spikes the confidence to near-100%, regardless of the trade's profit potential.
* **Opportunity Score (~70)**: Represents **Structural Quality / Reward-to-Risk**. It answers: *"Is this a high-quality setup?"* A market can be obviously going UP (98% confidence), but if RSI is heavily overbought and volume is weak, the setup quality is mediocre (e.g., 70), making it a dangerous time to enter a physical long-term position.
* **Investment Score**: Represents **Regime-adjusted Total Quality**. It factors in near-term catalysts (News/Geopolitics) based on the current market environment (e.g., heavily weighting Geopolitics during RISK_OFF).

## D. Why current global thresholds block Forex
In the live example:
* The engines strongly agreed the market was bullish (`BUY 85%` from committee, `98%` mathematical posterior).
* However, their underlying individual *scores* (quality metrics) ranged from 60 to 78, yielding an average Opportunity Score of ~70.
* The global `minimum_opportunity_score_for_action` is hardcoded to `75`.
* Therefore, the deterministic engine correctly identified that the setup quality (70) was below the premium threshold (75), overriding the high directional confidence (98%) and forcing a `WAIT`.
* **The Conflict**: The new `ModeExecutionPolicy` attempts to allow Forex trades at lower conviction/quality (60%). However, because the global layer requires a score of 75 *before* the Mode Execution Policy even runs, Forex is effectively trapped behind the stringent physical-gold requirements.

## E. Universal Safety vs Mode-Specific Execution
**Universal Safety (Belongs globally):**
* Minimum Aggregate Confidence (`minimum_confidence_for_action`)
* Maximum High-Severity Risks (`max_high_severity_risks_for_action`)
* Contradiction / Missing Evidence penalties

**Mode-Specific Execution (Belongs in ModeExecutionPolicy):**
* Minimum Opportunity Score (`minimum_opportunity_score_for_action`)
* Minimum Investment Score (`minimum_investment_score_for_buy`)
* Minimum Expected Move (Already migrated)

## F. Recommended Ownership
The `opportunity_score` and `investment_score` must still be calculated by `OpportunityFilter` and `InvestmentScoringEngine` (so the data exists in the pipeline), but the *enforcement* (`passed=opportunity_score >= threshold`) must be stripped out of `OpportunityFilter.assess` and `DecisionEngine._recommendation()`. 
Instead, the `ModeExecutionPolicy` should evaluate these scores against mode-specific thresholds.

## G. Recommended Configuration Fields
To resolve this, `config/decision_engine.json` should be restructured to include:
```json
"physical_minimum_opportunity_score": 75,
"forex_minimum_opportunity_score": 60,
"etf_minimum_opportunity_score": 70,
"physical_minimum_investment_score": 70,
"forex_minimum_investment_score": 55,
"etf_minimum_investment_score": 65
```

## H. Test Cases Required After Refactor
1. **Decision Flow Tests**: `tests/test_decision_flow.py` will likely break, as it expects `DecisionEngine` to output `WAIT` for scores < 75. It must be updated to expect `BUY` from the baseline engine, delegating the `WAIT` verification to the execution policy.
2. **Opportunity Filter Tests**: Assert that `OpportunityFilter` outputs the raw score without forcing a `passed=False` state purely based on the score.
3. **Execution Policy Tests**: `tests/test_execution_policy.py` must be expanded to assert that Forex allows scores >= 60, while Physical rejects scores < 75.
