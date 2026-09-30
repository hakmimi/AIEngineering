"""Live end-to-end smoke test through the real API (real LLM, audit store in a temp dir).

    python -m scripts.e2e_smoke        exit code 0 = every scenario behaved as expected
"""
import json
import logging
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import audit
import decision_graph
import main
from config import settings

store = audit.AuditStore(Path(tempfile.mkdtemp()) / "smoke_audit.db")      # never touch data/audit.db
for module in (audit, decision_graph, main):
    module.audit_store = store

logging.disable(logging.CRITICAL)
client = TestClient(main.app)
events = {e["transaction_id"]: e for e in json.loads((settings.data_dir / "sample_events.json").read_text(encoding="utf8"))}


def decide(payload: dict) -> dict:
    response = client.post("/decision", json=payload)
    assert response.status_code == 200, (response.status_code, response.text)
    return response.json()


def scenario(name, payload, check):
    body = decide(payload)
    ok = bool(check(body))
    audit_body = client.get(f"/decision/audit/{body['decision_id']}").json()
    ok = ok and audit_body["integrity_ok"] and audit_body["record"]["final_action"] == body["decision"]["action"]
    print(f"{'OK  ' if ok else 'FAIL'} {name:34} -> {body['decision']['action']:13} {str(body['decision']['selected_provider']):17} "
          f"llm={body['llm_status']:18} route={body['graph']['route']:9} {body['latency_ms']:>7.0f} ms")
    return ok


def with_id(event: dict, tid: str, **changes) -> dict:
    return {**event, "transaction_id": tid, **changes}


results = [
    scenario("routine routed (evt-001)", events["evt-001"], lambda b: b["decision"]["action"] == "route" and b["decision"]["selected_provider"] == "epsilon_local_il"),
    scenario("new customer big amount (evt-002)", events["evt-002"], lambda b: b["decision"]["action"] == "manual_review" and "NEW_CUSTOMER_HIGH_AMOUNT" in b["decision"]["reason_codes"]),
    scenario("high risk declined (evt-003)", events["evt-003"], lambda b: b["decision"]["action"] == "decline"),
    scenario("only option provider (evt-004)", events["evt-004"], lambda b: b["decision"]["selected_provider"] == "delta_global"),
    scenario("vip travel routed (evt-005)", events["evt-005"], lambda b: b["decision"]["action"] == "route"),
    scenario("sanctioned country blocked", with_id(events["evt-001"], "e2e-kp", country="KP"),
             lambda b: b["decision"]["action"] == "decline" and b["blocked_by"][0]["policy_id"] == "P1_SANCTIONED_COUNTRY" and b["llm_status"] == "skipped"),
    scenario("unknown country fallback", with_id(events["evt-001"], "e2e-zz", country="ZZ"), lambda b: b["graph"]["route"] == "fallback"),
    scenario("card-testing pattern", with_id(events["evt-001"], "e2e-ct", amount=1, currency="USD", country="US", merchant_category="digital_goods",
                                              customer_type="new", customer_age_days=1), lambda b: "CARD_TESTING_PATTERN" in b["decision"]["reason_codes"]),
]

invalid = client.post("/decision", json={**events["evt-001"], "amount": -5})
results.append(invalid.status_code == 422)
print(f"{'OK  ' if invalid.status_code == 422 else 'FAIL'} invalid input rejected (422)")
missing = client.get("/decision/audit/dec_missing")
results.append(missing.status_code == 404)
print(f"{'OK  ' if missing.status_code == 404 else 'FAIL'} unknown audit id -> 404")
by_tx = client.get("/decision/audit", params={"transaction_id": "e2e-kp"}).json()["decision_ids"]
results.append(len(by_tx) == 1)
print(f"{'OK  ' if len(by_tx) == 1 else 'FAIL'} audit lookup by transaction id")

print(f"\n{sum(results)}/{len(results)} scenarios passed; audit records written: {store.count()}")
sys.exit(0 if all(results) else 1)
