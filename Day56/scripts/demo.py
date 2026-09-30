"""Final demo: a five-minute guided tour through the real API (live model), with the audit store in a temp folder.

    python -m scripts.demo            run with the real LLM (needs OPENAI_API_KEY)
    python -m scripts.demo --offline  same tour with a stub model (no key, no network)

Exit code 0 = every step behaved as the story says. Each step prints what to point at while presenting.
"""
import argparse
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

BASE = {"transaction_id": "demo-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
        "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400, "prior_chargebacks": 0}
failures = []


def step(title: str, point: str) -> None:
    print(f"\n=== {title}\n    point at: {point}")


def check(condition: bool, text: str) -> None:
    print(f"    [{'ok' if condition else 'FAIL'}] {text}")
    if not condition:
        failures.append(text)


def use_stub_model() -> None:
    async def afake(prompt, schema, name):
        return fake(prompt, schema, name)

    def fake(prompt, schema, name):
        review = {"explanation": "Stub explanation.", "agrees_with_baseline": True, "concerns": [], "escalate_to_review": False, "confidence": 0.9}
        return review if name == "decision_review" else {"explanation": "Stub explanation."}

    decision_graph.get_structured, decision_graph.aget_structured = fake, afake


def run(offline: bool) -> int:
    logging.disable(logging.CRITICAL)
    if offline:
        use_stub_model()
    store = audit.AuditStore(Path(tempfile.mkdtemp()) / "demo_audit.db")           # never touch data/audit.db
    for module in (audit, decision_graph, main):
        module.audit_store = store
    with TestClient(main.app) as api:
        step("1. The service is up and honest about itself", "/ready says whether the model is configured - a missing key is degraded, not down")
        ready = api.get("/ready").json()
        print("   ", json.dumps(ready))
        check(ready["status"] == "ready", "service is ready")

        step("2. An ordinary payment is routed", "cheapest eligible provider; reason codes; audit id; graph trace; cost and latency")
        r = api.post("/decision", json=BASE).json()
        d = r["decision"]
        print(f"    {d['action']} -> {d['selected_provider']}  reasons={d['reason_codes']}  llm={r['llm_status']}  {r['latency_ms']} ms  ${r['usage']['estimated_cost_usd']}")
        print("    trace:", " > ".join(r["graph"]["trace"]))
        check(d["action"] == "route" and d["selected_provider"], "routine payment routed with a provider")

        step("2b. A less obvious payment is reviewed by the model", "the LLM writes the explanation (about 2 s and a fraction of a cent); it may only escalate")
        mid = {**BASE, "transaction_id": "demo-1b", "amount": 600.0, "currency": "EUR", "country": "DE", "merchant_category": "electronics",
               "customer_age_days": 90}
        r = api.post("/decision", json=mid).json()
        print(f"    {r['decision']['action']} llm={r['llm_status']} changed_by_ai={r['changed_by_ai']} {r['latency_ms']} ms ${r['usage']['estimated_cost_usd']}")
        print(f"    explanation: {r['decision']['explanation']}")
        check(r["llm_status"] == "ok" and r["decision"]["explanation"], "model-reviewed decision carries an explanation")

        step("3. A sanctioned country is declined before any tool or model runs", "policy first; no LLM cost; the trace is short")
        r = api.post("/decision", json={**BASE, "transaction_id": "demo-2", "country": "KP"}).json()
        print(f"    {r['decision']['action']} reasons={r['decision']['reason_codes']} llm={r['llm_status']} trace={r['graph']['trace']}")
        check(r["decision"]["action"] == "decline" and r["usage"]["llm_calls"] == 0, "declined by policy with zero LLM calls")

        step("4. Unknown means a human decides", "risk cannot be assessed, so the agent does not guess")
        r = api.post("/decision", json={**BASE, "transaction_id": "demo-3", "country": "ZZ"}).json()
        print(f"    {r['decision']['action']} reasons={r['decision']['reason_codes']} route={r['graph']['route']}")
        check(r["decision"]["action"] == "manual_review", "unknown country goes to manual review")

        step("5. An anomalous amount is escalated", "explicit pattern rule; the LLM did not have to notice")
        risky = {**BASE, "transaction_id": "demo-4", "amount": 2400.0, "currency": "USD", "country": "BR", "merchant_category": "gaming",
                 "customer_type": "new", "payment_method": "wallet", "customer_age_days": 2}
        r = api.post("/decision", json=risky).json()
        print(f"    {r['decision']['action']} reasons={r['decision']['reason_codes']}")
        check(r["decision"]["action"] != "route", "risky payment is not routed")

        step("6. Every decision can be audited and its integrity checked", "insert-only table, SHA-256 per row, agent version stored")
        a = api.get(f"/decision/audit/{r['decision_id']}").json()
        print(f"    integrity_ok={a['integrity_ok']} agent_version={a['record'].get('agent_version')}")
        check(a["integrity_ok"], "audit record verifies")

        step("7. Bad input and a forbidden mode are refused cleanly", "one error shape, request id in the header")
        bad = api.post("/decision", json={"transaction_id": "x"})
        forbidden = api.post("/decide?mode=baseline", json=BASE)
        print(f"    invalid transaction -> {bad.status_code}; disabled mode -> {forbidden.status_code} {forbidden.json()['detail']}")
        check(bad.status_code == 422 and forbidden.status_code == 403 and "X-Request-ID" in forbidden.headers, "422 and 403 with a request id")

        step("8. The configuration in force, without secrets", "layered config; only `configured: true/false` for keys")
        cfg = api.get("/config").json()
        print("   ", json.dumps({k: cfg["settings"][k] for k in ("decision_mode", "allowed_modes", "llm_model", "llm_temperature", "fast_path_enabled")}))
        check("openai_api_key" not in cfg["settings"], "no secret in /config")

        step("9. Operational numbers come from the audit table", "cost, latency, fast-path share")
        from metrics import load_audit_frame, summarize
        s = summarize(load_audit_frame(store.path))
        print(f"    decisions={s['decisions']} latency p50/p95={s['latency_ms']['p50']}/{s['latency_ms']['p95']} ms  cost=${s['cost']['total_usd']}")
        check(s["decisions"] >= 5, "metrics computed from the audit trail")
    print("\nDEMO", "FAILED: " + "; ".join(failures) if failures else "PASSED", f"({'offline stub model' if offline else 'live model'}, agent {settings.decision_mode})")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    sys.exit(run(parser.parse_args().offline))
