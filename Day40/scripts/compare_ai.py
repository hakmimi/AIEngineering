"""Run baseline and AI decisions on 10 transactions (5 sample events + 5 borderline synthetic routed ones) and compare.

    python -m scripts.compare_ai
"""
import json
import logging

from ai_decision import decide_ai
from config import settings
from data_loader import iter_transactions
from decision_engine import decide_baseline
from schemas import Action, Transaction


def pick_transactions() -> list[Transaction]:
    samples = [Transaction(**e) for e in json.loads((settings.data_dir / "sample_events.json").read_text(encoding="utf8"))]
    synthetic = [t for t in iter_transactions() if decide_baseline(t).decision.action is Action.ROUTE]
    synthetic.sort(key=lambda t: decide_baseline(t).decision.risk_score, reverse=True)   # the most borderline routed payments
    return samples + synthetic[:5]


def main() -> None:
    logging.disable(logging.CRITICAL)
    rows = []
    for tx in pick_transactions():
        r = decide_ai(tx)
        rows.append({"id": tx.transaction_id, "risk": r.decision.risk_score, "baseline": r.baseline.action.value,
                     "final": r.decision.action.value, "status": r.llm_status,
                     "agrees": r.review.agrees_with_baseline if r.review else None,
                     "escalate": r.review.escalate_to_review if r.review else None,
                     "concerns": len(r.review.concerns) if r.review else 0, "cost": r.usage["estimated_cost_usd"],
                     "ms": round(r.latency_ms), "notes": r.notes})
        print({k: v for k, v in rows[-1].items() if k != "notes"}, rows[-1]["notes"] or "")
    n = len(rows)
    summary = {"transactions": n, "llm_ok": sum(r["status"] == "ok" for r in rows),
               "agreed": sum(bool(r["agrees"]) for r in rows), "escalation_flags": sum(bool(r["escalate"]) for r in rows),
               "decisions_changed": sum(r["baseline"] != r["final"] for r in rows),
               "avg_cost_usd": round(sum(r["cost"] for r in rows) / n, 6), "avg_latency_ms": round(sum(r["ms"] for r in rows) / n)}
    print(json.dumps(summary, indent=2))
    (settings.data_dir / "ai_comparison.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf8")


if __name__ == "__main__":
    main()
