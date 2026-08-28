import json
import os

scenarios_dir = "data/benchmark_scenarios"
os.makedirs(scenarios_dir, exist_ok=True)

for f in os.listdir(scenarios_dir):
    os.remove(os.path.join(scenarios_dir, f))

def write_scenario(filename, data):
    with open(os.path.join(scenarios_dir, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def make_scenario(idx, s_type, s_id, direction, regime, b_evs, br_evs, crit_evs, evidence_pool, context):
    return {
        "scenario_id": s_id,
        "scenario_type": s_type,
        "expected_direction": direction,
        "expected_regime": regime,
        "market_context": context,
        "engine_outputs": {},
        "evidence": evidence_pool,
        "narratives": [],
        "bullish_evidence": b_evs,
        "bearish_evidence": br_evs,
        "critical_evidence": crit_evs,
        "expected_reasoning_points": ["Matches direction"],
        "unacceptable_reasoning": ["Ignores evidence"],
        "confidence_range": [0.6, 1.0] if direction != "WAIT" else [0.0, 0.4]
    }

# 3 Strong Bullish
write_scenario("01_bull_1.json", make_scenario(1, "bullish", "scen_bull_1", "BULLISH", "NORMAL", ["EV-1", "EV-2"], [], ["EV-1"], [{"id": "EV-1", "text": "Gold breakout above 2500"}, {"id": "EV-2", "text": "ETF inflows positive"}], "Strong rally context"))
write_scenario("02_bull_2.json", make_scenario(2, "bullish", "scen_bull_2", "BULLISH", "NORMAL", ["EV-1", "EV-2"], [], ["EV-2"], [{"id": "EV-1", "text": "Rate cuts priced in"}, {"id": "EV-2", "text": "Physical demand high"}], "Macro bullish"))
write_scenario("03_bull_3.json", make_scenario(3, "bullish", "scen_bull_3", "BULLISH", "INFLATION", ["EV-1", "EV-2"], [], ["EV-1"], [{"id": "EV-1", "text": "CPI surprise up"}, {"id": "EV-2", "text": "DXY falling"}], "Inflation shock"))

# 3 Strong Bearish
write_scenario("04_bear_1.json", make_scenario(4, "bearish", "scen_bear_1", "BEARISH", "NORMAL", [], ["EV-1", "EV-2"], ["EV-1"], [{"id": "EV-1", "text": "Gold drops below 2400"}, {"id": "EV-2", "text": "ETF outflows"}], "Strong selloff"))
write_scenario("05_bear_2.json", make_scenario(5, "bearish", "scen_bear_2", "BEARISH", "NORMAL", [], ["EV-1", "EV-2"], ["EV-2"], [{"id": "EV-1", "text": "Rate hikes expected"}, {"id": "EV-2", "text": "Physical demand weak"}], "Macro bearish"))
write_scenario("06_bear_3.json", make_scenario(6, "bearish", "scen_bear_3", "BEARISH", "DEFLATION", [], ["EV-1", "EV-2"], ["EV-1"], [{"id": "EV-1", "text": "CPI crash"}, {"id": "EV-2", "text": "DXY spiking"}], "Deflationary shock"))

# 2 WAIT
write_scenario("07_wait_1.json", make_scenario(7, "wait", "scen_wait_1", "WAIT", "NORMAL", ["EV-1"], ["EV-2"], [], [{"id": "EV-1", "text": "Mild support"}, {"id": "EV-2", "text": "Mild resistance"}], "Ambiguous sideways market"))
write_scenario("08_wait_2.json", make_scenario(8, "wait", "scen_wait_2", "WAIT", "NORMAL", ["EV-1"], ["EV-2"], [], [{"id": "EV-1", "text": "DXY flat"}, {"id": "EV-2", "text": "Yields flat"}], "No clear catalyst"))

# 2 Contradiction
write_scenario("09_contra_1.json", make_scenario(9, "contradiction", "scen_contra_1", "BULLISH", "NORMAL", ["EV-MACRO"], ["EV-TECH"], ["EV-MACRO"], [{"id": "EV-MACRO", "text": "Huge rate cut"}, {"id": "EV-TECH", "text": "Short-term technical sell signal"}], "Macro vs Tech"))
write_scenario("10_contra_2.json", make_scenario(10, "contradiction", "scen_contra_2", "BEARISH", "NORMAL", ["EV-TECH"], ["EV-MACRO"], ["EV-MACRO"], [{"id": "EV-TECH", "text": "Overbought bounce"}, {"id": "EV-MACRO", "text": "Massive rate hike"}], "Macro overrides tech"))

# 1 Geopolitical Shock
write_scenario("11_geo_1.json", make_scenario(11, "geopolitical_shock", "scen_geo_1", "BULLISH", "CRISIS", ["EV-GEO"], [], ["EV-GEO"], [{"id": "EV-GEO", "text": "War breaks out in Middle East"}], "Geopolitical shock context"))

# 1 Regime Transition
write_scenario("12_regime_1.json", make_scenario(12, "regime_transition", "scen_regime_1", "WAIT", "NORMAL", ["EV-1"], ["EV-2"], [], [{"id": "EV-1", "text": "Inflation metrics rising"}, {"id": "EV-2", "text": "Growth metrics falling"}], "Transitioning from NORMAL to STAGFLATION. Shifting from old to new regime."))

print("Wrote 12 scenarios.")
