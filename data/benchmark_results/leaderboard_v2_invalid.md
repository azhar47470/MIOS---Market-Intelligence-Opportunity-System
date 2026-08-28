# MIOS AI Committee Benchmark Leaderboard V2

## Benchmark Integrity
- Scenario validation: PASS
- Output schema validation: PASS
- Evidence grounding validation: PASS
- Contradiction rubric validation: PASS
- Provider reliability separation: PASS

## Overall Rankings
| Model | Overall | Quality | Reliability | Success Rate | Timeout Rate | Rate Limit Rate | Avg Latency (ms) | P95 Latency (ms) |
|---|---|---|---|---|---|---|---|---|
| opencode/laguna-s-2.1-free | 102.0 | 103.3 | 100.0 | 100% | 0% | 0% | 8682 | 15360 |
| opencode/nemotron-3-ultra-free | 89.8 | 88.6 | 91.7 | 92% | 0% | 0% | 29033 | 57296 |
| groq/openai/gpt-oss-120b | 89.0 | 81.7 | 100.0 | 100% | 0% | 0% | 1217 | 1700 |
| opencode/hy3-free | 87.5 | 79.2 | 100.0 | 100% | 0% | 0% | 14369 | 23791 |
| ollama-cloud/gpt-oss:120b | 87.5 | 79.2 | 100.0 | 100% | 0% | 0% | 2435 | 3237 |
| opencode/nemotron-3.5-lightning-free | 87.2 | 78.8 | 100.0 | 100% | 0% | 0% | 33983 | 59171 |
| opencode/deepseek-v4-flash-free | UNSTABLE | INSUFFICIENT_SAMPLE | 0.0 | 0% | 0% | 100% | 0 | 0 |
| opencode/mimo-v2.5-free | UNSTABLE | INSUFFICIENT_SAMPLE | 0.0 | 0% | 0% | 100% | 0 | 0 |
| gemini/gemini-3.7-flash | UNSTABLE | INSUFFICIENT_SAMPLE | 0.0 | 0% | 0% | 100% | 0 | 0 |

## Per-Scenario Breakdown
Shows the maximum quality score achieved by each model in each scenario group.
| Model | bull | bear | wait | contra | geo | regime |
|---|---|---|---|---|---|---|
| opencode/laguna-s-2.1-free | 120.0 | 120.0 | 70.0 | 120.0 | 75.0 | 65.0 |
| opencode/nemotron-3-ultra-free | 105.0 | 101.7 | 55.0 | 120.0 | 60.0 | 65.0 |
| groq/openai/gpt-oss-120b | 90.0 | 105.0 | 60.0 | 82.5 | 60.0 | 50.0 |
| opencode/hy3-free | 86.7 | 105.0 | 55.0 | 82.5 | 50.0 | 50.0 |
| ollama-cloud/gpt-oss:120b | 86.7 | 105.0 | 55.0 | 77.5 | 60.0 | 50.0 |
| opencode/nemotron-3.5-lightning-free | 91.7 | 101.7 | 57.5 | 75.0 | 50.0 | 50.0 |
| opencode/deepseek-v4-flash-free | - | - | - | - | - | - |
| opencode/mimo-v2.5-free | - | - | - | - | - | - |
| gemini/gemini-3.7-flash | - | - | - | - | - | - |