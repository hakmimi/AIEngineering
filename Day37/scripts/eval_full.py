"""Full evaluation: baseline (rules) vs AI (graph + LLM) on every case, with explanations scored and failures grouped.

    python -m scripts.eval_full <label>          e.g.  python -m scripts.eval_full v1

Writes data/eval/full_<label>.json, full_<label>.csv (one row per case) and report_<label>.md (human-readable summary).
"""
import csv
import json
import logging
import statistics
import sys
import time
from collections import Counter, defaultdict

from config import settings
from decision_engine import decide_baseline
from evaluation import Actual, CaseResult, load_cases, score_case, score_explanation, summarize
from explanations import template_explanation

EVAL_DIR = settings.data_dir / "eval"


def run_baseline(case) -> tuple[Actual, object]:
    started = time.perf_counter()
    decision = decide_baseline(case.transaction).decision
    decision.explanation = template_explanation(decision)
    actual = Actual(decision.action, decision.selected_provider, "normal", [r.value for r in decision.reason_codes], decision.explanation,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2))
    return actual, decision


def run_graph(case) -> tuple[Actual, object]:
    from decision_graph import run_decision_graph
    started = time.perf_counter()
    result = run_decision_graph(case.transaction)
    d = result.decision
    actual = Actual(d.action, d.selected_provider, result.graph_route, [r.value for r in d.reason_codes], d.explanation,
                    latency_ms=round((time.perf_counter() - started) * 1000, 1), cost_usd=result.usage.get("estimated_cost_usd", 0.0),
                    llm_status=result.llm_status)
    return actual, d


def evaluate_mode(cases, runner) -> list[CaseResult]:
    results = []
    for case in cases:
        actual, decision = runner(case)
        result = score_case(case, actual)
        result.explanation_score = score_explanation(actual.explanation, decision, case.transaction)
        results.append(result)
    return results


def mode_metrics(results: list[CaseResult]) -> dict:
    base = summarize(results)
    latencies = sorted(r.actual.latency_ms for r in results)
    return {**base,
            "explanation_avg_score": round(statistics.mean(r.explanation_score["total"] for r in results), 2),
            "explanation_pass_rate": round(sum(r.explanation_score["passed"] for r in results) / len(results), 3),
            "latency_p50_ms": round(statistics.median(latencies), 1), "latency_max_ms": latencies[-1],
            "total_cost_usd": round(sum(r.actual.cost_usd for r in results), 6),
            "llm_status": dict(Counter(r.actual.llm_status for r in results if r.actual.llm_status))}


def failure_groups(results: list[CaseResult]) -> dict:
    groups = defaultdict(list)
    for r in results:
        if r.passed:
            continue
        key = r.error_type or ("wrong_provider" if r.provider_ok is False else "wrong_route_or_reason")
        groups[f"{key} [{r.category}]"].append(r.case_id)
    return dict(groups)


def write_outputs(label: str, cases, base: list[CaseResult], ai: list[CaseResult]) -> dict:
    rows = []
    for case, b, a in zip(cases, base, ai, strict=True):
        rows.append({
            "case_id": case.id, "category": case.category, "expected_actions": "|".join(x.value for x in case.expected.acceptable_actions),
            "expected_route": case.expected.route,
            "baseline_action": b.actual.action.value, "baseline_provider": b.actual.provider, "baseline_pass": b.passed, "baseline_error": b.error_type,
            "ai_action": a.actual.action.value, "ai_provider": a.actual.provider, "ai_route": a.actual.route, "ai_pass": a.passed, "ai_error": a.error_type,
            "same_decision": (b.actual.action, b.actual.provider) == (a.actual.action, a.actual.provider),
            "baseline_expl_score": b.explanation_score["total"], "ai_expl_score": a.explanation_score["total"],
            "ai_latency_ms": a.actual.latency_ms, "ai_cost_usd": a.actual.cost_usd, "ai_llm_status": a.actual.llm_status,
            "ai_details": "; ".join(a.details)})
    with (EVAL_DIR / f"full_{label}.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"label": label, "baseline": mode_metrics(base), "ai": mode_metrics(ai),
               "decisions_differing": sum(not r["same_decision"] for r in rows),
               "route_accuracy_gain": round(summarize(ai)["route_accuracy"] - summarize(base)["route_accuracy"], 3),
               "baseline_failures": failure_groups(base), "ai_failures": failure_groups(ai)}
    lowest = sorted(((r.explanation_score["total"], r.case_id, r.actual.explanation) for r in ai), key=lambda t: t[0])[:3]
    summary["lowest_ai_explanations"] = [{"score": s, "case": c, "text": t} for s, c, t in lowest]
    (EVAL_DIR / f"full_{label}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, default=str), encoding="utf8")
    return summary


def report(summary: dict) -> str:
    b, a = summary["baseline"], summary["ai"]
    lines = [f"# Decision agent evaluation - {summary['label']}", "", "| Metric | Baseline (rules) | AI (graph + LLM) |", "|---|---:|---:|"]
    for key, name in [("pass_rate", "case pass rate"), ("action_accuracy", "action accuracy"), ("route_accuracy", "route accuracy"),
                      ("provider_accuracy", "provider accuracy"), ("explanation_avg_score", "explanation score (0-10)"),
                      ("explanation_pass_rate", "explanation pass rate"), ("latency_p50_ms", "latency p50 (ms)"), ("total_cost_usd", "LLM cost (USD)")]:
        lines.append(f"| {name} | {b[key]} | {a[key]} |")
    lines += ["", f"Errors - baseline: {b['errors']} | AI: {a['errors']}", f"Decisions that differ between the two agents: {summary['decisions_differing']}", "",
              "## Failures", f"Baseline: {json.dumps(summary['baseline_failures'], indent=1)}", f"AI: {json.dumps(summary['ai_failures'], indent=1)}", "",
              "## Lowest-scoring AI explanations (for manual reading)"]
    lines += [f"- {e['case']} ({e['score']}/10): {e['text']}" for e in summary["lowest_ai_explanations"]]
    return "\n".join(lines) + "\n"


def main(label: str) -> None:
    logging.disable(logging.CRITICAL)
    cases = load_cases()
    base = evaluate_mode(cases, run_baseline)
    ai = evaluate_mode(cases, run_graph)
    for case, b, a in zip(cases, base, ai, strict=True):
        print(f"{case.id:34} baseline={'PASS' if b.passed else 'FAIL':4} ai={'PASS' if a.passed else 'FAIL':4} "
              f"{a.actual.action.value:13} route={a.actual.route:9} expl={a.explanation_score['total']:>2} {'; '.join(a.details)}")
    summary = write_outputs(label, cases, base, ai)
    text = report(summary)
    (EVAL_DIR / f"report_{label}.md").write_text(text, encoding="utf8")
    print("\n" + text)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "v1")
