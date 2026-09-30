"""Run the evaluation set through every decision mode (baseline / ai / graph) - same cases, same scorer, different configuration.

    python -m scripts.compare_modes [label]      writes data/eval/modes_<label>.json  (default label: run)

Modes are enabled by overriding the settings object for this process only; production configuration is untouched.
"""
import json
import logging
import statistics
import sys
import time

from config import settings
from evaluation import Actual, load_cases, score_case, score_explanation, summarize
from modes import decide_with_mode
from schemas import Decision


def run_mode(mode: str):
    def runner(case):
        started = time.perf_counter()
        out = decide_with_mode(case.transaction, mode)
        d = Decision.model_validate(out["decision"])
        actual = Actual(d.action, d.selected_provider, (out.get("graph") or {}).get("route", "normal"), [r.value for r in d.reason_codes], d.explanation,
                        latency_ms=round((time.perf_counter() - started) * 1000, 1),
                        cost_usd=(out.get("usage") or {}).get("estimated_cost_usd", 0.0), llm_status=out.get("llm_status"))
        return actual, d
    return runner


def evaluate(mode: str, cases) -> dict:
    runner, results = run_mode(mode), []
    for case in cases:
        actual, decision = runner(case)
        res = score_case(case, actual)
        res.explanation_score = score_explanation(actual.explanation, decision, case.transaction)
        results.append(res)
    lat = sorted(r.actual.latency_ms for r in results)
    return {**summarize(results), "latency_p50_ms": round(statistics.median(lat), 1), "latency_max_ms": lat[-1],
            "total_cost_usd": round(sum(r.actual.cost_usd for r in results), 6),
            "explanation_avg_score": round(statistics.mean(r.explanation_score["total"] for r in results), 2),
            "failed_cases": [r.case_id for r in results if not r.passed]}


def main(label: str = "run") -> None:
    logging.disable(logging.INFO)
    object.__setattr__(settings, "allowed_modes", "baseline,ai,graph")
    object.__setattr__(settings, "fast_path_enabled", False)
    cases = load_cases()
    report = {"cases": len(cases), "modes": {m: evaluate(m, cases) for m in ("baseline", "ai", "graph")}}
    out = settings.data_dir / "eval" / f"modes_{label}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf8")
    print(f"{len(cases)} cases")
    print(f"{'mode':9}{'pass':>7}{'unsafe':>8}{'cautious':>10}{'expl':>7}{'p50 ms':>9}{'cost $':>10}")
    for m, r in report["modes"].items():
        errs = r["errors"]
        print(f"{m:9}{r['pass_rate']:>7.1%}{errs.get('unsafe_error', 0):>8}{errs.get('over_cautious', 0):>10}"
              f"{r['explanation_avg_score']:>7}{r['latency_p50_ms']:>9}{r['total_cost_usd']:>10}")
        if r["failed_cases"]:
            print(f"   failed: {r['failed_cases']}")
    print(f"written to {out}")


if __name__ == "__main__":
    main(*sys.argv[1:2])
