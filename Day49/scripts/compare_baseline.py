"""Run the baseline over the whole synthetic dataset and compare its decisions with the hidden truth.

    python -m scripts.compare_baseline           # prints 10 example decisions + aggregate quality
"""
import json
import logging

import pandas as pd

from config import settings
from data_loader import HIDDEN_COLUMNS, load_transactions
from decision_engine import decide_baseline
from schemas import Transaction


def main() -> None:
    logging.disable(logging.CRITICAL)
    df = load_transactions()
    rows = []
    for record in df.to_dict(orient="records"):
        tx = Transaction(**{k: v for k, v in record.items() if k not in HIDDEN_COLUMNS})
        result = decide_baseline(tx)
        d = result.decision
        rows.append({**record, "baseline_risk": d.risk_score, "action": d.action.value, "provider": d.selected_provider,
                     "expected_cost": d.expected_cost, "reasons": ",".join(r.value for r in d.reason_codes)})
    out = pd.DataFrame(rows)

    print("10 example decisions")
    print(out.sample(10, random_state=1)[["transaction_id", "amount", "currency", "country", "customer_type", "baseline_risk",
                                          "action", "provider", "reasons"]].to_string(index=False))

    spearman = out["baseline_risk"].corr(out["simulated_risk_score"], method="spearman")
    by_action = out.groupby("action").agg(n=("action", "size"), share=("action", lambda s: round(len(s) / len(out), 3)),
                                          fraud_rate=("is_fraud", "mean"), historical_approval=("approved_outcome", "mean"),
                                          mean_hidden_risk=("simulated_risk_score", "mean")).round(3)
    routed = out[out["action"] == "route"]
    summary = {
        "rows": len(out), "spearman_baseline_vs_hidden_risk": round(spearman, 3),
        "action_shares": {a: round(v, 3) for a, v in out["action"].value_counts(normalize=True).items()},
        "fraud_captured_by_decline_or_review": round(out.loc[out["is_fraud"], "action"].isin(["decline", "manual_review"]).mean(), 3),
        "fraud_in_routed": int(routed["is_fraud"].sum()), "fraud_total": int(out["is_fraud"].sum()),
        "provider_usage": routed["provider"].value_counts().to_dict(),
        "avg_expected_fee_pct_of_amount": round((routed["expected_cost"] / routed["amount"]).mean() * 100, 2),
    }
    print("\nby action\n", by_action.to_string())
    print("\n", json.dumps(summary, indent=2))
    (settings.data_dir / "baseline_comparison.json").write_text(json.dumps(summary, indent=2), encoding="utf8")


if __name__ == "__main__":
    main()
