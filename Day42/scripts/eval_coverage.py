"""Which situations does the evaluation set actually cover - and which not?  (No LLM needed: rules only.)

    python -m scripts.eval_coverage        prints the coverage report and writes data/eval/coverage.json

"Observed" values come from running the deterministic parts of the agent (policy gate, input routing, rules) on every case.
"""
import json
from collections import Counter

from config import settings
from decision_engine import decide_baseline
from evaluation import load_cases
from policy import check_policies, load_policies
from routing import FALLBACK, classify_input
from schemas import Action, Currency, CustomerType, MerchantCategory, PaymentMethod, ReasonCode
from simulation import COUNTRIES, PROVIDERS


def observe(case) -> dict:
    tx = case.transaction
    violations = check_policies(tx)
    if violations:
        return {"reasons": ["POLICY_BLOCK"], "provider": None, "policies": [v.policy_id for v in violations]}
    choice = classify_input(tx)
    if choice.route == FALLBACK:
        return {"reasons": [choice.reason_code.value], "provider": None, "policies": []}
    decision = decide_baseline(tx).decision
    return {"reasons": [r.value for r in decision.reason_codes], "provider": decision.selected_provider, "policies": []}


def main() -> None:
    cases = load_cases()
    observed = [observe(c) for c in cases]
    expected_actions = Counter(a.value for c in cases for a in c.expected.acceptable_actions)
    dims = {
        "customer_type": (Counter(c.transaction.customer_type.value for c in cases), [x.value for x in CustomerType]),
        "payment_method": (Counter(c.transaction.payment_method.value for c in cases), [x.value for x in PaymentMethod]),
        "merchant_category": (Counter(c.transaction.merchant_category.value for c in cases), [x.value for x in MerchantCategory]),
        "currency": (Counter(c.transaction.currency.value for c in cases), [x.value for x in Currency]),
        "country": (Counter(c.transaction.country for c in cases), sorted(COUNTRIES)),
        "provider_selected": (Counter(o["provider"] for o in observed if o["provider"]), [p.provider_id for p in PROVIDERS]),
        "reason_code": (Counter(r for o in observed for r in o["reasons"]), [r.value for r in ReasonCode]),
        "policy": (Counter(p for o in observed for p in o["policies"]), [p.id for p in load_policies()]),
    }
    report = {"cases": len(cases), "by_category": dict(Counter(c.category for c in cases)), "expected_actions": dict(expected_actions), "dimensions": {}}
    print(f"{len(cases)} cases; by category {report['by_category']}; expected actions {dict(expected_actions)}\n")
    for name, (seen, universe) in dims.items():
        missing = [u for u in universe if u not in seen]
        report["dimensions"][name] = {"covered": len(universe) - len(missing), "total": len(universe), "missing": missing}
        print(f"{name:18} {len(universe) - len(missing):>2}/{len(universe):<2} covered   missing: {missing or '-'}")
    declines = expected_actions.get(Action.DECLINE.value, 0)
    report["notes"] = [f"only {declines} expected-decline slots; real traffic is dominated by routine payments, this set is dominated by edge cases"]
    (settings.data_dir / "eval" / "coverage.json").write_text(json.dumps(report, indent=1), encoding="utf8")


if __name__ == "__main__":
    main()
