import pytest
import os
import json
from app.benchmark.reporting import generate_leaderboard

def test_reporting_reliability_separation(tmp_path):
    mock_results = [
        {"model": "good_model", "scenario": "scen_bull_1", "success": True, "latency_ms": 100, "score_total": 90.0, "scores": {"max_achievable": 90.0}, "error_code": None},
        {"model": "good_model", "scenario": "scen_bull_2", "success": True, "latency_ms": 100, "score_total": 45.0, "scores": {"max_achievable": 90.0}, "error_code": None},
        {"model": "bad_model", "scenario": "scen_bull_1", "success": False, "latency_ms": 100, "score_total": 0.0, "scores": {}, "error_code": "RATE_LIMITED"},
        {"model": "bad_model", "scenario": "scen_bull_2", "success": False, "latency_ms": 100, "score_total": 0.0, "scores": {}, "error_code": "TIMEOUT"},
    ]
    results_file = str(tmp_path / "test_results.json")
    with open(results_file, "w") as f:
        json.dump(mock_results, f)
        
    generate_leaderboard(results_file)
    with open("data/benchmark_results/leaderboard_v2.1.md", "r", encoding="utf-8") as f:
        content = f.read()
        
    assert "good_model" in content
    assert "bad_model" in content
    assert "UNSTABLE" in content
    assert "INSUFFICIENT_SAMPLE" in content
    
    # good_model scores are 100% and 50%, mean is 75.0%
    # Overall is 0.7 * 75 + 0.3 * 100 = 52.5 + 30 = 82.5
    assert "82.5" in content
    
    # Check bull mean is 75.0
    # The table has Bull Mean in it
    assert "75.0" in content

    # Check worst score is 50.0 and worst scenario is scen_bull_2
    assert "50.0" in content
    assert "scen_bull_2" in content
