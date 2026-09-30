# Day 54 - Final evaluation summary

## Goal
One document that states, with evidence, what the finished agent achieves - and what the evidence cannot show.

## What changed
| File | Change |
|---|---|
| `data/eval/full_v4.json`, `report_v4.md` | Fresh live evaluation of the final code (45 cases). |
| `data/eval/modes_final.json` | Baseline vs ai vs graph through the same scorer (`scripts/compare_modes.py`). |
| `scripts/final_summary.py` | Builds `docs/FINAL_EVALUATION.md` only from stored JSON files - no hand-typed numbers. |
| `docs/FINAL_EVALUATION.md` | History, like-for-like comparison, final table, layer attribution, operating profile, limits. |
| `tests/test_final_summary.py` (5 tests) | Document equals the evidence; no unsafe errors; no regression v3 -> v4; all cases were evaluated; only graph has zero unsafe errors; limits are stated. |
Suite: 495 tests. No production code changed.

## Headline results (live model, temperature 0)
| | Rules only | Full agent |
|---|---:|---:|
| Pass rate (45 cases) | 75.6% | 100% |
| Unsafe errors | 10 | 0 |
| Latency p50 | 0.1 ms | 1.9 s |
| Cost | $0 | $0.019 for 45 cases |

v3 -> v4 (same code, repeated run): identical pass rate, no regression; explanation score 9.60 -> 9.53 and p50 latency +164 ms are run-to-run noise.

## The findings worth remembering
1. **The safety layers earn the result, not the LLM.** Rules + LLM without the policy gate (`ai` mode) passes 75.6% - the same as rules alone.
2. **Template explanations score higher than the LLM's** (10 vs 9.53) on our rubric. The LLM stays for readability, and that is a judgement call, not a measured win.
3. **The history table misleads if read naively:** baseline falls 82.1% -> 75.6% between v2 and v3 because harder cases were added. The document therefore also gives a like-for-like number on the 31 original cases (agent 31/31, baseline 24/31).

## Honest limits
- The rules were tuned against this very set; 100% is a regression guard. The 8 hold-out cases were written after the fixes, by the same author.
- Synthetic data, one run per version, small n. No claim about real traffic, fraud loss or approval rates.
- Repeat the evaluation on every model, prompt or rule change (`python -m scripts.eval_full <label>`); the model can drift without any code change.
