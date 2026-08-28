import json
import os
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

@dataclass
class BenchmarkScenario:
    scenario_id: str
    scenario_type: str
    expected_direction: str
    expected_regime: str
    market_context: str
    engine_outputs: Dict[str, Any]
    evidence: List[Dict[str, str]]
    narratives: List[Dict[str, str]]
    bullish_evidence: List[str]
    bearish_evidence: List[str]
    critical_evidence: List[str]
    expected_reasoning_points: List[str]
    unacceptable_reasoning: List[str]
    confidence_range: List[float]

def validate_scenario(s: BenchmarkScenario) -> List[str]:
    errors = []
    
    evidence_ids = {e["id"] for e in s.evidence}
    
    # 1. Evidence existence
    for e_id in s.bullish_evidence + s.bearish_evidence + s.critical_evidence:
        if e_id not in evidence_ids:
            errors.append(f"Evidence ID {e_id} referenced but not in evidence pool.")
            
    # 2. Bullish vs Bearish overlap
    overlap = set(s.bullish_evidence) & set(s.bearish_evidence)
    if overlap:
        errors.append(f"Evidence {overlap} marked as both bullish and bearish.")
        
    # 3. Expected direction logic
    if s.expected_direction == "BULLISH" and not s.bullish_evidence:
        errors.append("BULLISH direction expected but no bullish evidence provided.")
    if s.expected_direction == "BEARISH" and not s.bearish_evidence:
        errors.append("BEARISH direction expected but no bearish evidence provided.")
        
    # 4. Scenario-specific integrity
    if s.scenario_type == "bullish" and s.expected_direction != "BULLISH":
        errors.append("Bullish scenario must expect BULLISH direction.")
    if s.scenario_type == "bearish" and s.expected_direction != "BEARISH":
        errors.append("Bearish scenario must expect BEARISH direction.")
    if s.scenario_type == "wait" and s.expected_direction != "WAIT":
        errors.append("Wait scenario must expect WAIT direction.")
        
    if s.scenario_type == "contradiction":
        if not s.bullish_evidence or not s.bearish_evidence:
            errors.append("Contradiction scenario must have both bullish and bearish evidence.")
            
    if s.scenario_type == "regime_transition":
        # Check that context mentions two regimes
        if "regime" not in s.market_context.lower() or "transition" not in s.market_context.lower():
            if not ("two distinct regimes" in s.market_context.lower() or "shifting from" in s.market_context.lower()):
                pass # soft check
                
    return errors

def load_scenarios(scenarios_dir: str = "data/benchmark_scenarios") -> List[BenchmarkScenario]:
    if not os.path.exists(scenarios_dir):
        return []
    
    scenarios = []
    for filename in sorted(os.listdir(scenarios_dir)):
        if filename.endswith(".json") and not filename.startswith("rubric"):
            filepath = os.path.join(scenarios_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                s = BenchmarkScenario(
                    scenario_id=data.get("scenario_id", ""),
                    scenario_type=data.get("scenario_type", ""),
                    expected_direction=data.get("expected_direction", ""),
                    expected_regime=data.get("expected_regime", ""),
                    market_context=data.get("market_context", ""),
                    engine_outputs=data.get("engine_outputs", {}),
                    evidence=data.get("evidence", []),
                    narratives=data.get("narratives", []),
                    bullish_evidence=data.get("bullish_evidence", []),
                    bearish_evidence=data.get("bearish_evidence", []),
                    critical_evidence=data.get("critical_evidence", []),
                    expected_reasoning_points=data.get("expected_reasoning_points", []),
                    unacceptable_reasoning=data.get("unacceptable_reasoning", []),
                    confidence_range=data.get("confidence_range", [0.0, 1.0])
                )
                
                # Check validation strictly upon loading
                errors = validate_scenario(s)
                if errors:
                    raise ValueError(f"Scenario Integrity Error in {s.scenario_id}: {errors}")
                
                scenarios.append(s)
    return scenarios
