"""Record real example requests and responses (live LLM) into docs/examples/ and docs/EXAMPLES.md.

    python -m scripts.make_examples

A test validates every stored example against the response models, so an example cannot drift from the contract.
"""
import json
import logging

from fastapi.testclient import TestClient

import main
from config import settings

CASES = [
    ("routine_route", "Ordinary domestic grocery payment: routed to the cheapest eligible provider.",
     {"transaction_id": "ex-routine", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
      "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400, "prior_chargebacks": 0}),
    ("policy_decline", "Sanctioned country: declined by the policy gate before any tool or model runs.",
     {"transaction_id": "ex-sanctioned", "timestamp": "2026-01-05T09:12:00Z", "amount": 80.0, "currency": "USD", "country": "KP",
      "merchant_category": "electronics", "customer_type": "returning", "payment_method": "card", "customer_age_days": 300, "prior_chargebacks": 0}),
    ("unknown_country_review", "Country missing from the risk tables: risk cannot be assessed, so a human decides.",
     {"transaction_id": "ex-unknown", "timestamp": "2026-01-05T09:12:00Z", "amount": 120.0, "currency": "EUR", "country": "ZZ",
      "merchant_category": "travel", "customer_type": "returning", "payment_method": "card", "customer_age_days": 200, "prior_chargebacks": 0}),
    ("risky_new_account_review", "New account with an unusually large gaming payment: the amount-anomaly rule sends it to manual review.",
     {"transaction_id": "ex-risky", "timestamp": "2026-01-05T09:12:00Z", "amount": 2400.0, "currency": "USD", "country": "BR",
      "merchant_category": "gaming", "customer_type": "new", "payment_method": "wallet", "customer_age_days": 2, "prior_chargebacks": 0}),
]


def main_() -> None:
    logging.disable(logging.CRITICAL)
    out = settings.base_dir / "docs" / "examples"
    out.mkdir(parents=True, exist_ok=True)
    lines = ["# Examples (generated with a live model - run `python -m scripts.make_examples`)", "",
             "Each example is a real request/response pair; the files in `examples/` are validated against the response models by a test.", ""]
    with TestClient(main.app) as client:
        for name, why, payload in CASES:
            response = client.post("/decision", json=payload)
            body = response.json()
            (out / f"{name}.json").write_text(json.dumps({"request": payload, "response": body}, indent=2), encoding="utf8")
            d = body["decision"]
            lines += [f"## {name.replace('_', ' ')}", "", why, "", "Request:", "```json", json.dumps(payload, indent=2), "```",
                      f"Response (`{response.status_code}`, trimmed to the important fields):", "```json",
                      json.dumps({"decision": d, "decision_id": body["decision_id"], "changed_by_ai": body["changed_by_ai"], "llm_status": body["llm_status"],
                                  "fast_path": body["fast_path"], "graph": {"route": body["graph"]["route"], "trace": body["graph"]["trace"]},
                                  "latency_ms": body["latency_ms"]}, indent=2), "```", ""]
            print(f"{name}: {d['action']} {d['reason_codes']}")
    (settings.base_dir / "docs" / "EXAMPLES.md").write_text("\n".join(lines), encoding="utf8")


if __name__ == "__main__":
    main_()
