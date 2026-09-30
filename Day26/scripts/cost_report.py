"""Measure tokens, cost and answer quality on the 22-case eval set under different cost settings.

    python -m scripts.cost_report                 runs all configs below and prints a comparison table
Writes data/eval/cost_report.json.  Costs use usage.PRICES (estimates).
"""
import json
import logging
import statistics
import time

from config import settings
from graph import run_graph
from scripts.evaluate import EVAL_DIR, score_case

CONFIGS = {
    # name: overrides applied to `settings` for the run
    "A_baseline":     {"json_schema_in_prompt": True,  "max_context_tokens": 0,   "max_context_chunks": 8},
    "B_no_schema":    {"json_schema_in_prompt": False, "max_context_tokens": 0,   "max_context_chunks": 8},
    "C_cap_400":      {"json_schema_in_prompt": False, "max_context_tokens": 400, "max_context_chunks": 8},
    "D_cap_250":      {"json_schema_in_prompt": False, "max_context_tokens": 250, "max_context_chunks": 8},
}


def run_config(name: str, overrides: dict, cases: list[dict]) -> dict:
    saved = {k: getattr(settings, k) for k in overrides}
    for k, v in overrides.items():
        object.__setattr__(settings, k, v)            # settings is a frozen dataclass; this is an experiment-only override
    try:
        rows = []
        for case in cases:
            started = time.perf_counter()
            result = run_graph(case["question"])
            row = score_case(case, result, (time.perf_counter() - started) * 1000)
            row["usage"] = result["usage"]
            rows.append(row)
    finally:
        for k, v in saved.items():
            object.__setattr__(settings, k, v)
    llm_rows = [r for r in rows if r["usage"]["llm_calls"]]
    return {
        "config": name, **overrides,
        "accuracy": round(sum(r["passed"] for r in rows) / len(rows), 3),
        "requests_with_llm": len(llm_rows),
        "avg_input_tokens": round(statistics.mean(r["usage"]["llm_input_tokens"] for r in llm_rows), 1),
        "avg_output_tokens": round(statistics.mean(r["usage"]["llm_output_tokens"] for r in llm_rows), 1),
        "avg_cost_usd": round(statistics.mean(r["usage"]["estimated_cost_usd"] for r in rows), 6),
        "total_cost_usd": round(sum(r["usage"]["estimated_cost_usd"] for r in rows), 5),
        "latency_p50_ms": round(statistics.median(r["latency_ms"] for r in rows), 1),
        "failed": [r["id"] for r in rows if not r["passed"]],
    }


def main() -> None:
    logging.disable(logging.CRITICAL)
    cases = json.loads((EVAL_DIR / "eval_set.json").read_text(encoding="utf8"))
    results = []
    for name, overrides in CONFIGS.items():
        res = run_config(name, overrides, cases)
        results.append(res)
        print(f"{name:12} acc={res['accuracy']:.3f} in_tok={res['avg_input_tokens']:>6} out_tok={res['avg_output_tokens']:>5} "
              f"avg_cost=${res['avg_cost_usd']:.6f} p50={res['latency_p50_ms']:.0f}ms failed={res['failed']}")
    base = results[0]["avg_cost_usd"]
    for res in results:
        res["cost_vs_baseline"] = round(res["avg_cost_usd"] / base - 1, 3)
    (EVAL_DIR / "cost_report.json").write_text(json.dumps(results, indent=1), encoding="utf8")
    print("\ncost vs baseline:", {r["config"]: f"{r['cost_vs_baseline']:+.1%}" for r in results})


if __name__ == "__main__":
    main()
