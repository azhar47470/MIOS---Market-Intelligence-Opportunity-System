import argparse
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def load_env(env_path=".env"):
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = value

load_env()

from app.benchmark.scenarios import load_scenarios
from app.benchmark.harness import run_benchmark
from app.benchmark.reporting import generate_leaderboard
from app.benchmark.providers import get_providers

def doctor_command():
    providers = get_providers()
    opencode = next(p for p in providers if p.name == "opencode")
    groq = next(p for p in providers if p.name == "groq")
    ollama = next((p for p in providers if p.name == "ollama-cloud"), None)
    gemini = next(p for p in providers if p.name == "gemini")

    def test_gateway(p, url):
        headers = {}
        if p.get_api_key():
            headers["Authorization"] = f"Bearer {p.get_api_key()}"
        status, body, exc = p._get(url, headers)
        import json
        avail_models = []
        if status == 200:
            try:
                data = json.loads(body)
                avail_models = [m["id"] for m in data.get("data", [])]
            except:
                pass
        return status, avail_models

    print("==================================================")
    print("OPEN CODE ZEN")
    print(f"  credentials: {'SET' if opencode.get_api_key() else 'MISSING'}")
    zen_url = "https://opencode.ai/zen/v1/models"
    print(f"  gateway: {zen_url}")
    
    # We call check_availability to see our mocked EXCLUDED states too
    avail_zen = opencode.check_availability()
    zen_status, zen_models = test_gateway(opencode, zen_url)
    print(f"  /models: HTTP {zen_status}")
    print("  candidate models:")
    for m in opencode.models:
        status_str = avail_zen.get(m, "UNAVAILABLE")
        print(f"     {m}: {status_str}")

    print("\n==================================================")
    print("OPEN CODE CONSOLE")
    print(f"  credentials: {'SET' if opencode.get_api_key() else 'MISSING'}")
    console_url = "https://opencode.ai/inference/openai/v1/models"
    print(f"  gateway: {console_url}")
    con_status, con_models = test_gateway(opencode, console_url)
    print(f"  /models: HTTP {con_status}")
    print("  candidate models:")
    for m in opencode.models:
        status_str = "AVAILABLE" if m in con_models else ("FORBIDDEN" if con_status == 403 else "UNAVAILABLE")
        print(f"     {m}: {status_str}")

    print("\n==================================================")
    print("GROQ")
    print(f"  credentials: {'SET' if groq.get_api_key() else 'MISSING'}")
    groq_status, groq_models = test_gateway(groq, "https://api.groq.com/openai/v1/models")
    print(f"  /models: HTTP {groq_status}")
    for m in groq.models:
        status_str = "AVAILABLE" if m in groq_models else ("FORBIDDEN" if groq_status == 403 else "UNAVAILABLE")
        print(f"  {m}: {status_str}")
        
    if ollama:
        print("\n==================================================")
        print("OLLAMA CLOUD")
        print(f"  credentials: {'SET' if ollama.get_api_key() else 'MISSING'}")
        ollama_status, ollama_models = test_gateway(ollama, "https://ollama.com/v1/models")
        print(f"  /models: HTTP {ollama_status}")
        for m in ollama.models:
            status_str = "AVAILABLE" if m in ollama_models else ("FORBIDDEN" if ollama_status == 403 else "UNAVAILABLE")
            print(f"  {m}: {status_str}")

    print("\n==================================================")
    print("GEMINI")
    print(f"  credentials: {'SET' if gemini.get_api_key() else 'MISSING'}")
    print(f"  endpoint: https://generativelanguage.googleapis.com/v1beta/models")
    print(f"  model: gemini-3.7-flash")

    print("\n==================================================")
    print("OPTIONAL: PROVIDER SMOKE TEST")
    
    def run_smoke(p, m):
        print(f"Smoke test {p.name}/{m}...")
        res = p.generate(m, "Return JSON: {\"status\":\"ok\"}", "Hello")
        if res.success:
            print(f"  -> SUCCESS ({res.latency_ms}ms) | Parsed JSON: {res.parsed_json}")
        else:
            print(f"  -> FAILED ({res.latency_ms}ms) | {res.error_code}: {res.error_message}")
            
    # Smoke test OpenCode Zen
    best_opencode = next((m for m in opencode.models if m in zen_models and "EXCLUDED" not in avail_zen.get(m, "")), opencode.models[0])
    if best_opencode in zen_models and "EXCLUDED" not in avail_zen.get(best_opencode, ""):
        run_smoke(opencode, best_opencode)
    
    # Smoke test Groq
    if groq.models[0] in groq_models:
        run_smoke(groq, groq.models[0])
        
    # Smoke test Ollama
    if ollama and ollama.models[0] in ollama_models:
        run_smoke(ollama, ollama.models[0])
        
    # Smoke test Gemini
    if gemini.get_api_key():
        run_smoke(gemini, gemini.models[0])

def main():
    parser = argparse.ArgumentParser(description="MIOS AI Committee Model Benchmark Harness")
    parser.add_argument("--pilot", action="store_true", help="Run a 3-scenario pilot")
    parser.add_argument("--full", action="store_true", help="Run the full 12-scenario benchmark")
    parser.add_argument("--model", type=str, help="Run only the specified model")
    parser.add_argument("--scenario", type=str, help="Run only the specified scenario ID")
    parser.add_argument("--report", action="store_true", help="Regenerate the report from existing results")
    parser.add_argument("--doctor", action="store_true", help="Check configuration and endpoint availability")
    
    args = parser.parse_args()
    
    if args.doctor:
        doctor_command()
        return
        
    if args.report:
        print("Generating report...")
        generate_leaderboard(results_file='data/benchmark_results/results_v2.1.json')
        return

    scenarios = load_scenarios()
    if not scenarios:
        print("No scenarios found. Check data/benchmark_scenarios/")
        return
        
    if args.scenario:
        scenarios = [s for s in scenarios if s.id == args.scenario]
        
    models = [args.model] if args.model else ['nemotron-3.5-lightning-free', 'nemotron-3-ultra-free', 'hy3-free', 'laguna-s-2.1-free', 'openai/gpt-oss-120b', 'gpt-oss:120b']
    
    if args.pilot:
        print("Starting PILOT benchmark (3 scenarios)...")
        run_benchmark(scenarios[:3], models=models, is_pilot=True)
    elif args.full:
        print("Starting FULL benchmark (12 scenarios)...")
        run_benchmark(scenarios, models=models, is_pilot=False)
    else:
        print("Please specify --pilot, --full, --doctor, or --report")
        parser.print_help()

if __name__ == "__main__":
    main()




