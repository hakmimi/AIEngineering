"""Analyse a simulation run: latency, route/decision distribution, LLM/fast-path share, cost, slow cases, and whether each
injected scenario was handled the way the business expects.

    python -m scripts.analyze_simulation run1
"""
import json
import statistics
import sys
from collections import Counter, defaultdict

from config import settings

OUT_DIR = settings.data_dir / "simulation"

# what MUST happen to each injected scenario (routine traffic has no per-event expectation)
EXPECTATIONS = {
    "policy_violation": lambda r: r["action"] in ("decline", "manual_review") and "POLICY_BLOCK" in (r.get("reason_codes") or ""),
    "edge_case": lambda r: r["action"] == "manual_review" and (r.get("route") == "fallback" or "POLICY_BLOCK" in (r.get("reason_codes") or "")),
    "card_testing": lambda r: r["action"] in ("manual_review", "decline"),
    "anomalous_amount": lambda r: r["action"] in ("manual_review", "decline"),
}


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * q))], 1) if ordered else 0.0


def analyze(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("status") == 200]
    server = [r["server_ms"] for r in ok if r.get("server_ms") is not None]
    wall = [r["wall_ms"] for r in ok]
    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for r in ok:
        by_scenario[r["scenario"]].append(r)
    checks = {}
    for scenario, check in EXPECTATIONS.items():
        rs = by_scenario.get(scenario, [])
        if rs:
            failed = [r["transaction_id"] for r in rs if not check(r)]
            checks[scenario] = {"events": len(rs), "as_expected": len(rs) - len(failed), "failed": failed}
    llm_events = [r for r in ok if (r.get("llm_calls") or 0) > 0]
    return {
        "events": len(rows), "succeeded": len(ok), "failed": len(rows) - len(ok),
        "latency_ms": {"server_avg": round(statistics.mean(server), 1), "server_p50": percentile(server, 0.5), "server_p95": percentile(server, 0.95),
                       "server_max": max(server), "wall_avg": round(statistics.mean(wall), 1), "wall_p95": percentile(wall, 0.95)},
        "actions": dict(Counter(r["action"] for r in ok)), "routes": dict(Counter(r["route"] for r in ok)),
        "llm_status": dict(Counter(r["llm_status"] for r in ok)), "fast_path_share": round(sum(bool(r.get("fast_path")) for r in ok) / len(ok), 3),
        "llm_reviewed_share": round(len(llm_events) / len(ok), 3),
        "cost": {"total_usd": round(sum(r.get("cost_usd") or 0 for r in ok), 5), "avg_usd": round(sum(r.get("cost_usd") or 0 for r in ok) / len(ok), 6)},
        "latency_llm_vs_no_llm_ms": {"with_llm_avg": round(statistics.mean([r["server_ms"] for r in llm_events]), 1) if llm_events else None,
                                     "without_llm_avg": round(statistics.mean([r["server_ms"] for r in ok if not (r.get("llm_calls") or 0)]), 1)
                                     if len(llm_events) < len(ok) else None},
        "scenario_actions": {s: dict(Counter(r["action"] for r in rs)) for s, rs in by_scenario.items()},
        "scenario_checks": checks,
        "audit_recorded_share": round(sum(bool(r.get("audit_recorded")) for r in ok) / len(ok), 3),
        "slowest": [{"id": r["transaction_id"], "server_ms": r["server_ms"], "scenario": r["scenario"], "action": r["action"], "llm_status": r["llm_status"]}
                    for r in sorted(ok, key=lambda r: r["server_ms"] or 0, reverse=True)[:5]],
    }


def report(label: str, a: dict) -> str:
    lat = a["latency_ms"]
    lines = [f"# Simulation report - {label}", "",
             f"- events: {a['events']} (ok {a['succeeded']}, failed {a['failed']}); audit recorded for {a['audit_recorded_share']:.0%}",
             f"- server latency: avg {lat['server_avg']} ms, p50 {lat['server_p50']}, p95 {lat['server_p95']}, max {lat['server_max']}; client wall avg {lat['wall_avg']} ms",
             f"- LLM-reviewed {a['llm_reviewed_share']:.0%} of decisions, fast path {a['fast_path_share']:.0%}; avg latency with LLM "
             f"{a['latency_llm_vs_no_llm_ms']['with_llm_avg']} ms vs {a['latency_llm_vs_no_llm_ms']['without_llm_avg']} ms without",
             f"- cost: ${a['cost']['total_usd']} total, ${a['cost']['avg_usd']} per decision",
             f"- decisions: {a['actions']}; routes: {a['routes']}; llm_status: {a['llm_status']}", "", "## Scenario checks"]
    for scenario, c in a["scenario_checks"].items():
        lines.append(f"- {scenario}: {c['as_expected']}/{c['events']} handled as expected" + (f" - FAILED: {c['failed']}" if c["failed"] else ""))
    lines += ["", "## Slowest requests"] + [f"- {s['id']} {s['server_ms']} ms ({s['scenario']}, {s['action']}, llm={s['llm_status']})" for s in a["slowest"]]
    return "\n".join(lines) + "\n"


def main(label: str) -> None:
    data = json.loads((OUT_DIR / f"{label}.json").read_text(encoding="utf8"))
    result = analyze(data["rows"])
    text = report(label, result)
    (OUT_DIR / f"{label}_analysis.json").write_text(json.dumps(result, indent=1), encoding="utf8")
    (OUT_DIR / f"{label}_report.md").write_text(text, encoding="utf8")
    print(text)


if __name__ == "__main__":
    main(sys.argv[1])
