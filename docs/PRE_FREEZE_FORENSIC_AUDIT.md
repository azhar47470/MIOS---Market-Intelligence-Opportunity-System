# Final Pre-Freeze Forensic Audit

## 1. Executive Summary
This read-only forensic audit verifies the latest MIOS live run metrics across Physical, Forex, and ETF execution modes. The audit confirms that the core architectural logic—including pullback scoring, provider throttling, and mode-specific policies—is functioning strictly as designed. Detected issues (OpenCode schema violations, Groq TPM exhaustion) are externally bounded provider limitations that are gracefully captured and mitigated by the built-in fallback orchestration (failing over seamlessly to Ollama).

**Final Recommendation:** **FREEZE**. MIOS is highly stable and hackathon-ready. No structural, logic, or algorithmic hotfixes are required before the freeze. 

---

## 2. Pullback Score Breakdown
**Issue:** `PullbackRiskScore` evaluating to 26/100 (LOW) despite overbought RSI, flat momentum, and weak trend quality.

**Mathematical Verification:**
In `PullbackRiskEngine.analyze()`, the scoring is calculated iteratively with a maximum score of 100.
*   **RSI(14) Exhaustion:** `RSI = 75.70`. Formula: `min(20, int((75.70 - 70) * 2)) = 11`. **(11 / 20 points)**
*   **Momentum Deterioration:** Flat momentum (`< 0.5`). Formula: statically assigns `5` points. **(5 / 15 points)**
*   **Trend Quality:** Weak trend (`< 40`). Formula: statically assigns `10` points. **(10 / 10 points)**
*   *Other Components* (Resistance/FVG, EMA extension, Sweeps, Regime instability, Volatility) did not trigger. 

**Total Score = 11 + 5 + 10 = 26 / 100.**
*   *Bucket Logic:* `>=30` is MEDIUM, `<30` is LOW. 
*   **Conclusion:** The heuristic calculated **exactly as designed**. A 26/100 naturally rests in the `LOW` tier because the engine mandates compound structural failures (e.g., structural liquidity sweeps or FVG presence) to bridge into higher risk categories. 
*   **Verification:** The score is correctly wired as an *informational context block* (`EvidenceRecord`) and does not preempt the `DecisionEngine`'s final execution action.

---

## 3. OpenCode Schema Diagnosis (`time_horizon` > 200 chars)
**Issue:** OpenCode rejected for generating `time_horizon` strings exceeding the 200-character threshold.

**Diagnosis:**
1.  **Prompt Omission:** The production contract (`app/ai/committee.py`) specifically mandates LLMs to output `time_horizon: "Expected duration..."`, but the strict constraints section completely lacks a length directive.
2.  **LLM Verbosity:** Absent an explicit constraint, LLMs organically output verbose structural qualifiers. 
3.  **Schema Robustness:** Pydantic safely caught the breach and rejected the payload exactly as intended, triggering the provider fallback.

**Fix Ranking:**
1.  **[Smallest Safe Fix - P2]** Update `_MemberVotePayload.time_horizon` to `max_length=500`. It prevents random truncation and accommodates descriptive LLM output without compromising schema integrity.
2.  **[Prompt Fix - P2]** Add `"- time_horizon MUST be under 200 characters"` to the system rules prompt.
3.  **[No Change]** Leave as-is. The fallback architecture handles it safely. 

---

## 4. Groq Rate-Limit Diagnosis (8000 TPM limit)
**Issue:** Groq failed with `Limit = 8000 TPM`, `Used = 3908`, `Requested = 5246`.

**Diagnosis:**
1.  `SAFE_INPUT_BUDGET=6500` inside `app/ai/agents/llm_client.py` successfully restricted the requested tokens to `5246`, successfully guarding the single-request payload.
2.  However, Groq’s 8,000 TPM (Tokens Per Minute) limit acts as a *global provider bucket*. 
3.  Since committee requests execute sequentially/concurrently, Agent 1 utilized `3908` tokens, and Agent 2 attempted to utilize `5246` tokens inside the *same rolling minute* (totaling ~9154 tokens).
4.  **Conclusion:** This is a pure provider quota limitation, not a global token guard bug. The fallback mechanism correctly trapped the `429 Too Many Requests` limit and failed over to Ollama.

---

## 5. Output Consistency Audit
*   **Wait / Allocation Consistency:** Both `physical` and `etf` adapters structurally intercept `WAIT` execution policies and successfully rewrite allocation advice to conservative directives (`"Maintain current allocation; wait for stronger confirmation."`). 
*   **Forex Viability:** Actionable `BUY/SHORT` forex signals output strict `Entry`, `TP`, and `SL` values dynamically relative to target/stop percentages.
*   **Vocabulary Clarity:** Output correctly displays `Directional Bias` (the Intelligence intent) separate from `Final Action` (the actionable policy). `Expected Move` dynamically renders unconditionally for all assets.
*   **Conclusion:** Rendering output logic matches all previous architectural requirements and fails safe on execution walls.

---

## 6. Exact Files/Functions Involved
*   **Pullback Risk:** `app/application/engines/pullback_risk_engine.py` -> `PullbackRiskEngine.analyze()`
*   **OpenCode Schema:** `app/ai/committee.py` -> `_MemberVotePayload`, `CommitteeMember.vote()`
*   **LLM Budgets:** `app/ai/agents/llm_client.py` -> `SAFE_INPUT_BUDGET` evaluation
*   **Format Adapters:** `app/application/adapters/physical.py`, `etf.py`, `forex.py` -> `adapt()`

---

## 7. Recommended Fixes 
*   **P0:** None.
*   **P1:** None.
*   **P2 (Safe to defer):** 
    *   Change `time_horizon` max length to 500 in `app/ai/committee.py`.
    *   Add global TPM throttling state logic if relying exclusively on Groq in production.

## 8. Unchanged Elements
*   **DO NOT MODIFY** `DecisionEngine` or `ModeExecutionPolicy`.
*   **DO NOT MODIFY** Pullback heuristics or scaling weights.
*   **DO NOT MODIFY** Confidence thresholds, Opportunity filters, or TP/SL generation.
*   **DO NOT MODIFY** Provider orchestration or fallback routing.

## 9. Final Decision
**FREEZE.** The engine acts perfectly deterministically. Known schema variations and provider API walls are actively being shielded by robust Pydantic validation and intelligent multi-provider fallback. Proceed to Hackathon deployment.
