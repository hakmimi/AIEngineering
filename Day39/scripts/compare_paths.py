"""Latency / cost / quality of three configurations on the evaluation cases, and a projection for realistic traffic.

    python -m scripts.compare_paths

  A  rules only            (baseline, template explanation)
  B  AI, LLM on every case (fast path off)
  C  AI with the fast path (LLM skipped when the rules are unambiguous)

Costs use usage.PRICES (estimates). The projection applies the measured per-LLM-call cost and latency to the share of the
1,000 synthetic transactions that would take the fast path (no LLM needed to know that: it is decided by the rules).
"""
import json
import logging
import statistics
import time

from config import settings
from data_loader import iter_transactions
from decision_engine import decide_baseline
from decision_graph import run_decision_graph
from evaluation import load_cases, score_case
from fast_path import evaluate_fast_path
from scripts.eval_full import run_baseline

EVAL_DIR = settings.data_dir / "eval"


def run_config(name: str, cases, runner) -> dict:
    rows = []
    for case in cases:
        started = time.perf_counter()
        actual = runner(case)
        rows.append((score_case(case, actual), (time.perf_counter() - started) * 1000, actual))
    lat = sorted(ms for _, ms, _ in rows)
    llm_calls = sum(1 for _, _, a in rows if a.llm_status == "ok" or a.llm_status in ("rejected_output", "unavailable"))
    return {"config": name, "pass_rate": round(sum(r.passed for r, _, _ in rows) / len(rows), 3),
            "unsafe_errors": sum(r.error_type == "unsafe_error" for r, _, _ in rows),
            "latency_p50_ms": round(statistics.median(lat), 1), "latency_p95_ms": round(lat[int(len(lat) * 0.95)], 1),
            "llm_reviewed_cases": llm_calls, "avg_cost_usd": round(statistics.mean(a.cost_usd for _, _, a in rows), 6),
            "total_cost_usd": round(sum(a.cost_usd for _, _, a in rows), 6),
            "decisions": {r.case_id: (r.actual.action.value, r.actual.provider) for r, _, _ in rows}}


def graph_runner(case):
    from evaluation import Actual
    result = run_decision_graph(case.transaction)
    d = result.decision
    return Actual(d.action, d.selected_provider, result.graph_route, [r.value for r in d.reason_codes], d.explanation,
                  cost_usd=result.usage.get("estimated_cost_usd", 0.0), llm_status=result.llm_status)


def main() -> None:
    logging.disable(logging.CRITICAL)
    cases = load_cases()
    a = run_config("A_rules_only", cases, lambda c: run_baseline(c)[0])
    object.__setattr__(settings, "fast_path_enabled", False)
    b = run_config("B_ai_all_cases", cases, graph_runner)
    object.__setattr__(settings, "fast_path_enabled", True)
    c = run_config("C_ai_fast_path", cases, graph_runner)
    differing = [k for k in b["decisions"] if b["decisions"][k] != c["decisions"][k]]

    fast = total = 0
    reasons: dict[str, int] = {}
    for tx in iter_transactions():
        verdict = evaluate_fast_path(tx, decide_baseline(tx))
        total += 1
        fast += verdict.fast
        reasons[verdict.reason] = reasons.get(verdict.reason, 0) + 1
    per_call_cost = b["total_cost_usd"] / max(b["llm_reviewed_cases"], 1)
    projection = {"transactions": total, "fast_path_share": round(fast / total, 3), "reasons": reasons,
                  "llm_cost_per_1000_all": round(per_call_cost * 1000, 3), "llm_cost_per_1000_fast_path": round(per_call_cost * 1000 * (1 - fast / total), 3)}

    for cfg in (a, b, c):
        print({k: v for k, v in cfg.items() if k != "decisions"})
    print("decisions that differ between B and C:", differing or "none")
    print("projection on the synthetic population:", json.dumps(projection))
    for cfg in (a, b, c):
        cfg.pop("decisions")
    (EVAL_DIR / "path_comparison.json").write_text(json.dumps({"configs": [a, b, c], "b_vs_c_differing": differing, "projection": projection}, indent=1), encoding="utf8")


def sweep() -> None:
    """How much of realistic traffic could skip the LLM at different fast-path risk limits (rules only, no LLM calls)?"""
    logging.disable(logging.CRITICAL)
    object.__setattr__(settings, "fast_path_enabled", True)
    baselines = [(tx, decide_baseline(tx)) for tx in iter_transactions()]
    fraud = {t.transaction_id: bool(f) for t, f in zip(iter_transactions(), __import__("data_loader").load_transactions()["is_fraud"], strict=True)}
    table = {}
    for limit in (0.10, 0.15, 0.20, 0.25, 0.30):
        object.__setattr__(settings, "fast_path_max_risk", limit)
        fast = [(tx, b) for tx, b in baselines if evaluate_fast_path(tx, b).fast]
        routed_fast = [tx for tx, b in fast if b.decision.action.value == "route"]
        table[limit] = {"fast_share": round(len(fast) / len(baselines), 3), "fast_routed": len(routed_fast),
                        "fraud_among_fast_routed": sum(fraud[t.transaction_id] for t in routed_fast)}
    object.__setattr__(settings, "fast_path_max_risk", 0.15)
    print(json.dumps(table, indent=1))
    (EVAL_DIR / "fast_path_sweep.json").write_text(json.dumps(table, indent=1), encoding="utf8")


if __name__ == "__main__":
    import sys
    sweep() if sys.argv[1:] == ["sweep"] else main()
