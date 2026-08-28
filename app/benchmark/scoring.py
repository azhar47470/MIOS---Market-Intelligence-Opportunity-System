from typing import Dict, Any, List, Optional
from app.benchmark.scenarios import BenchmarkScenario
from app.benchmark.providers import BenchmarkResult

def score_round1(res: BenchmarkResult, scenario: BenchmarkScenario) -> tuple[float, Dict[str, float]]:
    parsed_json = res.parsed_json
    max_ach = 95.0 if scenario.scenario_type == "contradiction" else 85.0
    if not parsed_json:
        return 0.0, {"json": 0.0, "direction": 0.0, "grounding": 0.0, "reasoning": 0.0, "confidence": 0.0, "contradiction": 0.0, "max_achievable": max_ach}

    # Strict JSON contract
    expected_keys = {"direction", "confidence", "reasoning", "evidence", "assumptions", "weaknesses"}
    if not expected_keys.issubset(set(parsed_json.keys())):
        return 0.0, {"json": 0.0, "direction": 0.0, "grounding": 0.0, "reasoning": 0.0, "confidence": 0.0, "contradiction": 0.0, "max_achievable": max_ach}

    scores = {"json": 10.0}
    
    # Direction
    d = parsed_json.get("direction")
    if d == scenario.expected_direction:
        scores["direction"] = 25.0
    else:
        scores["direction"] = 0.0

    # Confidence discipline
    conf = parsed_json.get("confidence", 0.0)
    try:
        conf = float(conf)
        if scenario.confidence_range[0] <= conf <= scenario.confidence_range[1]:
            scores["confidence"] = 10.0
        else:
            scores["confidence"] = 0.0
    except:
        scores["confidence"] = 0.0

    # Evidence grounding (exact IDs)
    evidence_ids = {e["id"] for e in scenario.evidence}
    cited_evidence = parsed_json.get("evidence", [])
    valid_citations = 0
    if isinstance(cited_evidence, list):
        for cited in cited_evidence:
            if cited in evidence_ids:
                if (d == "BULLISH" and cited in scenario.bullish_evidence) or \
                   (d == "BEARISH" and cited in scenario.bearish_evidence) or \
                   (cited in scenario.critical_evidence):
                   valid_citations += 1
    
    expected_ev_count = max(1, len(scenario.critical_evidence))
    grounding_ratio = min(1.0, valid_citations / expected_ev_count)
    scores["grounding"] = 20.0 * grounding_ratio

    # Reasoning
    reasoning = str(parsed_json.get("reasoning", ""))
    reasoning_score = 0.0
    if len(reasoning) > 20 and valid_citations > 0 and scores["direction"] > 0:
        reasoning_score = 20.0
    scores["reasoning"] = reasoning_score

    # Contradiction (only score if contradiction scenario)
    if scenario.scenario_type == "contradiction":
        if "weaknesses" in parsed_json and len(parsed_json["weaknesses"]) > 0:
            scores["contradiction"] = 10.0
        else:
            scores["contradiction"] = 0.0
    else:
        scores["contradiction"] = 0.0
        
    scores["max_achievable"] = max_ach

    total = sum([v for k, v in scores.items() if k != "max_achievable"])
    return total, scores

def score_round2(res: BenchmarkResult, scenario: BenchmarkScenario) -> tuple[float, Dict[str, float]]:
    parsed_json = res.parsed_json
    if not parsed_json:
        return 0.0, {"debate": 0.0, "max_achievable_r2": 5.0}

    if "interactions" not in parsed_json or not isinstance(parsed_json["interactions"], list):
        return 0.0, {"debate": 0.0, "max_achievable_r2": 5.0}

    scores = {}
    
    valid_debate = False
    evidence_ids = {e["id"] for e in scenario.evidence}
    for interaction in parsed_json["interactions"]:
        if isinstance(interaction, dict):
            expected = {"type", "target", "reason", "evidence", "severity"}
            if expected.issubset(set(interaction.keys())):
                ev = interaction.get("evidence")
                if ev in evidence_ids:
                    valid_debate = True

    scores["debate"] = 5.0 if valid_debate else 0.0
    scores["max_achievable_r2"] = 5.0
    return scores["debate"], scores
