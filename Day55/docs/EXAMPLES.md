# Examples (generated with a live model - run `python -m scripts.make_examples`)

Each example is a real request/response pair; the files in `examples/` are validated against the response models by a test.

## routine route

Ordinary domestic grocery payment: routed to the cheapest eligible provider.

Request:
```json
{
  "transaction_id": "ex-routine",
  "timestamp": "2026-01-05T09:12:00Z",
  "amount": 216.0,
  "currency": "ILS",
  "country": "IL",
  "merchant_category": "groceries",
  "customer_type": "returning",
  "payment_method": "card",
  "customer_age_days": 400,
  "prior_chargebacks": 0
}
```
Response (`200`, trimmed to the important fields):
```json
{
  "decision": {
    "transaction_id": "ex-routine",
    "action": "route",
    "selected_provider": "epsilon_local_il",
    "reason_codes": [
      "LOW_RISK",
      "CHEAPEST_ELIGIBLE",
      "HIGHEST_APPROVAL_RATE"
    ],
    "risk_score": 0.0625,
    "expected_cost": 4.2,
    "expected_approval_probability": 0.9235,
    "explanation": "Routed to epsilon_local_il because the transaction has a low risk score; it is the cheapest eligible provider; it has the highest expected approval probability (risk score 0.06). Expected fee 4.20, expected approval probability 92%."
  },
  "decision_id": "dec_7c24c3310fba40dc",
  "changed_by_ai": false,
  "llm_status": "skipped_fast_path",
  "fast_path": "routine_low_risk",
  "graph": {
    "route": "normal",
    "trace": [
      "input",
      "policy_gate",
      "route_input",
      "risk_tool",
      "rules",
      "provider_tool",
      "cost_tool",
      "select",
      "fast_explain",
      "finalize",
      "constraint_guard"
    ]
  },
  "latency_ms": 11.7
}
```

## policy decline

Sanctioned country: declined by the policy gate before any tool or model runs.

Request:
```json
{
  "transaction_id": "ex-sanctioned",
  "timestamp": "2026-01-05T09:12:00Z",
  "amount": 80.0,
  "currency": "USD",
  "country": "KP",
  "merchant_category": "electronics",
  "customer_type": "returning",
  "payment_method": "card",
  "customer_age_days": 300,
  "prior_chargebacks": 0
}
```
Response (`200`, trimmed to the important fields):
```json
{
  "decision": {
    "transaction_id": "ex-sanctioned",
    "action": "decline",
    "selected_provider": null,
    "reason_codes": [
      "POLICY_BLOCK"
    ],
    "risk_score": 0.5,
    "expected_cost": null,
    "expected_approval_probability": null,
    "explanation": "Payments from sanctioned jurisdictions are prohibited. Policy: P1_SANCTIONED_COUNTRY."
  },
  "decision_id": "dec_69860aa733d6406d",
  "changed_by_ai": false,
  "llm_status": "skipped",
  "fast_path": null,
  "graph": {
    "route": "normal",
    "trace": [
      "input",
      "policy_gate",
      "policy_block",
      "finalize",
      "constraint_guard"
    ]
  },
  "latency_ms": 4.2
}
```

## unknown country review

Country missing from the risk tables: risk cannot be assessed, so a human decides.

Request:
```json
{
  "transaction_id": "ex-unknown",
  "timestamp": "2026-01-05T09:12:00Z",
  "amount": 120.0,
  "currency": "EUR",
  "country": "ZZ",
  "merchant_category": "travel",
  "customer_type": "returning",
  "payment_method": "card",
  "customer_age_days": 200,
  "prior_chargebacks": 0
}
```
Response (`200`, trimmed to the important fields):
```json
{
  "decision": {
    "transaction_id": "ex-unknown",
    "action": "manual_review",
    "selected_provider": null,
    "reason_codes": [
      "UNKNOWN_COUNTRY"
    ],
    "risk_score": 0.5,
    "expected_cost": null,
    "expected_approval_probability": null,
    "explanation": "Sent to manual review because the customer's country is not covered by the risk tables (risk score 0.50)."
  },
  "decision_id": "dec_c9331bb097924ba5",
  "changed_by_ai": false,
  "llm_status": "skipped",
  "fast_path": null,
  "graph": {
    "route": "fallback",
    "trace": [
      "input",
      "policy_gate",
      "route_input",
      "fallback",
      "finalize",
      "constraint_guard"
    ]
  },
  "latency_ms": 4.9
}
```

## risky new account review

New account with an unusually large gaming payment: the amount-anomaly rule sends it to manual review.

Request:
```json
{
  "transaction_id": "ex-risky",
  "timestamp": "2026-01-05T09:12:00Z",
  "amount": 2400.0,
  "currency": "USD",
  "country": "BR",
  "merchant_category": "gaming",
  "customer_type": "new",
  "payment_method": "wallet",
  "customer_age_days": 2,
  "prior_chargebacks": 0
}
```
Response (`200`, trimmed to the important fields):
```json
{
  "decision": {
    "transaction_id": "ex-risky",
    "action": "manual_review",
    "selected_provider": null,
    "reason_codes": [
      "AMOUNT_ANOMALY"
    ],
    "risk_score": 0.5275,
    "expected_cost": null,
    "expected_approval_probability": null,
    "explanation": "The transaction was flagged for manual review because the payment amount of $2400 exceeds the limit set for new customers, triggering the AMOUNT_ANOMALY reason code. The risk score of 0.5275 reflects moderate risk primarily due to the amount and customer type. No providers were selected as the rules require human approval for this payment."
  },
  "decision_id": "dec_9fafe22deb7146b5",
  "changed_by_ai": false,
  "llm_status": "ok",
  "fast_path": null,
  "graph": {
    "route": "normal",
    "trace": [
      "input",
      "policy_gate",
      "route_input",
      "risk_tool",
      "rules",
      "llm_explain",
      "finalize",
      "constraint_guard"
    ]
  },
  "latency_ms": 3516.5
}
```
