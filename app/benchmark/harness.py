ROUND1_PROMPT = """You are participating in the MIOS model benchmark.

Return ONLY valid JSON matching this exact structure:

{
  "direction": "BULLISH",
  "confidence": 0.0,
  "reasoning": "string",
  "evidence": ["EV-..."],
  "assumptions": ["string"],
  "weaknesses": ["string"]
}

Rules:
- direction MUST be exactly one of:
  BULLISH
  BEARISH
  WAIT

- confidence MUST be a number from 0.0 to 1.0
- evidence MUST contain only evidence IDs provided in the scenario
- assumptions and weaknesses MUST be arrays of strings
- reasoning must explain the decision using only supplied scenario information
- do not invent evidence
- do not invent market data
- do not use APPROVE
- do not use REJECT
- do not use HOLD
- do not use BUY
- do not use SELL
- do not wrap the JSON in markdown
- do not output any text before or after the JSON"""
ROUND2_PROMPT = """You are participating in the MIOS benchmark debate.

Review the provided Round 1 committee opinions.

Return ONLY valid JSON:

{
  "interactions": [
    {
      "type": "objection",
      "target": "member-id",
      "reason": "string",
      "evidence": "EV-...",
      "severity": "HIGH"
    }
  ]
}

Rules:
- type MUST be objection or support
- target MUST reference a provided committee member
- evidence MUST be an evidence ID that exists in the scenario
- severity MUST be HIGH, MEDIUM, or LOW
- maximum 1 objection and 1 support per member
- do not assign numeric impact
- do not invent evidence
- do not use markdown
- output JSON only"""
import json
import os
import time
from typing import List, Optional

from .providers import get_providers, get_provider_by_model, LLMProvider, BenchmarkResult
from .scenarios import BenchmarkScenario, load_scenarios
from .scoring import score_round1, score_round2
from .reporting import generate_leaderboard

def run_benchmark(scenarios: List[BenchmarkScenario], models: Optional[List[str]] = None, is_pilot: bool = False):
    providers = get_providers()
    print(f"Starting {'PILOT' if is_pilot else 'FULL'} benchmark ({len(scenarios)} scenarios)...")
    
    results_file = "data/benchmark_results/pilot_results_v2.1.json" if is_pilot else "data/benchmark_results/results_v2.1.json"
    os.makedirs("data/benchmark_results/raw", exist_ok=True)
    
    results = []
    
    # Flatten provider models
    active_models = []
    for provider in providers:
        if hasattr(provider, "models") and provider.models:
            for m in provider.models:
                if models and m not in models:
                    continue
                active_models.append((provider, m))
        else:
             m = getattr(provider, "model_id", provider.__class__.__name__)
             if models and m not in models:
                 continue
             active_models.append((provider, m))
             
    for scenario in scenarios:
        print(f"\n--- Scenario: {scenario.scenario_id} ---")
        for provider, model_name in active_models:
            # Skip rate limited models for speed, this was handled in old harness.py via status checks but we can just let it try and fail gracefully.
            print(f"  [Round 1] Benchmarking {model_name}...")
            
            prompt1 = json.dumps({"context": scenario.market_context, "evidence": scenario.evidence})
            res1 = provider.generate(model=model_name, system_prompt=ROUND1_PROMPT, user_prompt=prompt1)
            
            total1, scores1 = score_round1(res1, scenario)
            
            p_name = getattr(provider, "name", provider.__class__.__name__)
            res_dict = {
                "model": f"{p_name}/{model_name}",
                "scenario": scenario.scenario_id,
                "round": 1,
                "success": res1.success,
                "error_code": res1.error_code,
                "latency_ms": res1.latency_ms,
                "scores": scores1,
                "score_total": total1
            }
            results.append(res_dict)
            
            safe_model_name = model_name.replace(':', '_').replace('/', '_')
            with open(f"data/benchmark_results/raw/{scenario.scenario_id}_{safe_model_name}_r1.json", "w", encoding="utf-8") as f:
                json.dump(res_dict, f, indent=2)

            if res1.success:
                print(f"  [Round 2] Benchmarking {model_name}...")
                prompt2 = json.dumps({"round1_vote": res1.parsed_json})
                res2 = provider.generate(model=model_name, system_prompt=ROUND2_PROMPT, user_prompt=prompt2)
                
                total2, scores2 = score_round2(res2, scenario)
                
                res2_dict = {
                    "model": res_dict["model"],
                    "scenario": scenario.scenario_id,
                    "round": 2,
                    "success": res2.success,
                    "error_code": res2.error_code,
                    "latency_ms": res2.latency_ms,
                    "scores": scores2,
                    "score_total": total2
                }
                
                res_dict["scores"].update(scores2)
                res_dict["score_total"] += total2
                
                with open(f"data/benchmark_results/raw/{scenario.scenario_id}_{safe_model_name}_r2.json", "w", encoding="utf-8") as f:
                    json.dump(res2_dict, f, indent=2)
                    
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    generate_leaderboard(results_file=results_file)
    print("\nBenchmark complete. Leaderboard generated.")

