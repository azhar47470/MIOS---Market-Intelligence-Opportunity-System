import pytest
import os
import json
from app.benchmark.scenarios import load_scenarios, BenchmarkScenario, validate_scenario
from app.benchmark.scoring import score_round1, score_round2
from app.benchmark.providers import BenchmarkResult

def test_scenario_integrity():
    scenarios = load_scenarios()
    assert len(scenarios) == 12, "Should have 12 scenarios"
    
def test_bearish_bullish_consistency():
    scenarios = load_scenarios()
    for s in scenarios:
        if s.scenario_type == "bullish":
            assert s.expected_direction == "BULLISH"
            assert len(s.bullish_evidence) > 0

def test_exact_direction_scoring():
    scen = BenchmarkScenario("id", "bullish", "BULLISH", "NORMAL", "", {}, [], [], [], [], [], [], [], [0.0, 1.0])
    res = BenchmarkResult("mock", "mock", True, parsed_json={"direction": "BULLISH", "confidence": 0.5, "reasoning": "r", "evidence": [], "assumptions": [], "weaknesses": []})
    _, scores = score_round1(res, scen)
    assert scores["direction"] == 25.0

def test_evidence_grounding():
    scen = BenchmarkScenario("id", "bullish", "BULLISH", "NORMAL", "", {}, 
                             [{"id": "EV-1", "text": "a"}, {"id": "EV-2", "text": "b"}], [], ["EV-1"], [], ["EV-1"], [], [], [0.0, 1.0])
    res = BenchmarkResult("mock", "mock", True, parsed_json={"direction": "BULLISH", "confidence": 0.5, "reasoning": "r", "evidence": ["EV-1"], "assumptions": [], "weaknesses": []})
    _, scores = score_round1(res, scen)
    assert scores["grounding"] == 20.0

def test_contradiction_scoring():
    scen = BenchmarkScenario("id", "contradiction", "WAIT", "NORMAL", "", {}, [], [], [], [], [], [], [], [0.0, 1.0])
    res = BenchmarkResult("mock", "mock", True, parsed_json={"direction": "WAIT", "confidence": 0.5, "reasoning": "r", "evidence": [], "assumptions": [], "weaknesses": ["some weakness"]})
    _, scores = score_round1(res, scen)
    assert scores["contradiction"] == 10.0
    
    # Check that it's zero outside contradiction scenarios
    scen_normal = BenchmarkScenario("id", "bullish", "BULLISH", "NORMAL", "", {}, [], [], [], [], [], [], [], [0.0, 1.0])
    _, scores_normal = score_round1(res, scen_normal)
    assert scores_normal["contradiction"] == 0.0

def test_debate_scoring():
    scen = BenchmarkScenario("id", "bullish", "BULLISH", "NORMAL", "", {}, [{"id": "EV-1", "text": "a"}], [], [], [], [], [], [], [0.0, 1.0])
    res = BenchmarkResult("mock", "mock", True, parsed_json={"interactions": [{"type": "objection", "target": "X", "reason": "Y", "evidence": "EV-1", "severity": "HIGH"}]})
    _, scores = score_round2(res, scen)
    assert scores["debate"] == 5.0
    
    # check zero when no debate result exists
    res_empty = BenchmarkResult("mock", "mock", True, parsed_json={})
    _, scores_empty = score_round2(res_empty, scen)
    assert scores_empty["debate"] == 0.0
    
def test_max_quality():
    scen = BenchmarkScenario("id", "contradiction", "WAIT", "NORMAL", "", {}, [{"id": "EV-1", "text": "a"}], [], ["EV-1"], [], ["EV-1"], [], [], [0.0, 1.0])
    res1 = BenchmarkResult("mock", "mock", True, parsed_json={"direction": "WAIT", "confidence": 0.5, "reasoning": "reasoning must be at least 20 chars long to count!", "evidence": ["EV-1"], "assumptions": ["a"], "weaknesses": ["w"]})
    res2 = BenchmarkResult("mock", "mock", True, parsed_json={"interactions": [{"type": "objection", "target": "X", "reason": "Y", "evidence": "EV-1", "severity": "HIGH"}]})
    t1, s1 = score_round1(res1, scen)
    t2, s2 = score_round2(res2, scen)
    
    total = t1 + t2
    max_ach = s1["max_achievable"] + s2["max_achievable_r2"]
    
    final_quality = (total / max_ach) * 100
    assert final_quality <= 100.0
    assert final_quality > 99.0
