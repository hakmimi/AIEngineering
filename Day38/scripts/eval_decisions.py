"""Evaluation runner skeleton.

    python -m scripts.eval_decisions run <label> [--mode baseline|graph] [--limit N]
"""
import argparse
import json
import logging
import time

from config import settings
from decision_engine import decide_baseline
from evaluation import Actual, actual_from_baseline, load_cases, score_case, summarize

EVAL_DIR = settings.data_dir / "eval"


def run_agent(case, mode: str) -> Actual:
    started = time.perf_counter()
    if mode == "baseline":
        actual = actual_from_baseline(decide_baseline(case.transaction).decision)
    else:                                   # "graph": the full workflow with the LLM
        from decision_graph import run_decision_graph
        result = run_decision_graph(case.transaction)
        actual = Actual(result.decision.action, result.decision.selected_provider, result.graph_route,
                        [r.value for r in result.decision.reason_codes], result.decision.explanation,
                        cost_usd=result.usage.get("estimated_cost_usd", 0.0), llm_status=result.llm_status)
    actual.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    return actual


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run"])
    parser.add_argument("label")
    parser.add_argument("--mode", choices=["baseline", "graph"], default="baseline")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)

    cases = load_cases(limit=args.limit)
    results = []
    for case in cases:
        result = score_case(case, run_agent(case, args.mode))
        results.append(result)
        print(f"{'PASS' if result.passed else 'FAIL'} {case.id:34} -> {result.actual.action.value:13} {str(result.actual.provider):17} "
              f"route={result.actual.route:9} {'; '.join(result.details)}")
    summary = {"label": args.label, "mode": args.mode, **summarize(results)}
    print(json.dumps(summary, indent=1))
    (EVAL_DIR / f"decisions_{args.label}.json").write_text(json.dumps(
        {"summary": summary, "results": [{**r.__dict__, "actual": r.actual.__dict__} for r in results]}, indent=1, default=str), encoding="utf8")


if __name__ == "__main__":
    main()
