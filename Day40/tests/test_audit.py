"""Day 40: audit records - content, storage, integrity, retrieval endpoints, failure behaviour, log correlation."""
import json
import logging
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

import ai_decision
import audit
import decision_graph
from audit import AuditNotFound, AuditRecord, AuditStore, new_decision_id
from decision_graph import run_decision_graph
from main import app
from schemas import Action, Transaction

ROUTINE = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
           "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
           "prior_chargebacks": 0}
GOOD_REVIEW = {"explanation": "Explained.", "agrees_with_baseline": True, "concerns": ["one thing"], "escalate_to_review": False, "confidence": 0.9}
client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_audit(tmp_path, monkeypatch):
    """Override of the conftest default: these tests exercise the real SQLite store (integrity, reopening, insert-only)."""
    store = AuditStore(tmp_path / "audit.db")
    for module in (audit, decision_graph, sys.modules["main"]):
        monkeypatch.setattr(module, "audit_store", store)
    return store


@pytest.fixture(autouse=True)
def llm(monkeypatch):
    fake = lambda prompt, schema, name: GOOD_REVIEW if name == "decision_review" else {"explanation": "Check."}  # noqa: E731
    monkeypatch.setattr(decision_graph, "get_structured", fake)
    monkeypatch.setattr(ai_decision, "get_structured", fake)


def decide(**changes):
    return run_decision_graph(Transaction(**{**ROUTINE, **changes}))


# --- ids and records -------------------------------------------------------------------------------------------------------------
def test_every_decision_gets_a_unique_id_and_is_recorded(isolated_audit):
    a, b = decide(), decide()
    assert a.decision_id.startswith("dec_") and a.decision_id != b.decision_id and a.audit_recorded and b.audit_recorded
    assert isolated_audit.count() == 2


def test_record_contains_everything_needed_to_reconstruct_the_decision(isolated_audit):
    r = decide()
    rec = isolated_audit.get(r.decision_id)
    assert rec.transaction_id == "t-1" and rec.agent_version == "v2" and rec.route == "normal"
    assert rec.input_summary["amount"] == 216.0 and rec.input_summary["country"] == "IL" and "transaction_id" not in rec.input_summary
    assert rec.graph_trace == r.graph_trace and [t["tool"] for t in rec.tools_used][:2] == ["risk_lookup", "provider_lookup"]
    assert rec.risk_score == r.decision.risk_score and set(rec.risk_components) == {"country", "category", "customer", "amount", "chargebacks"}
    assert rec.final_action == "route" and rec.final_provider == "epsilon_local_il" and rec.baseline_action == "route"
    assert rec.reason_codes[0] == "LOW_RISK" and rec.changed_by_ai is False and rec.business_explanation == "Explained."
    assert rec.llm["status"] == "ok" and rec.llm["agrees_with_baseline"] is True and rec.llm["concerns"] == ["one thing"]
    assert rec.usage["llm_calls"] == 0 and rec.latency_ms >= 0 and rec.created_at.endswith("+00:00")


def test_tool_arguments_are_summarised_and_bounded(isolated_audit):
    r = decide()
    for call in isolated_audit.get(r.decision_id).tools_used:
        assert set(call) == {"tool", "ok", "ms", "arguments"} and len(call["arguments"]) <= 163


def test_fallback_uncertain_and_fast_path_decisions_are_audited_too(isolated_audit, settings_override):
    fallback = decide(country="ZZ")
    rec = isolated_audit.get(fallback.decision_id)
    assert rec.route == "fallback" and rec.reason_codes == ["UNKNOWN_COUNTRY"] and rec.llm == {"status": "skipped"} and rec.tools_used == []
    settings_override(fast_path_enabled=True)
    fast = isolated_audit.get(decide().decision_id)
    assert fast.fast_path == "routine_low_risk" and fast.llm["status"] == "skipped_fast_path"


def test_ai_changed_decisions_are_flagged(isolated_audit, monkeypatch):
    escalate = {**GOOD_REVIEW, "escalate_to_review": True}
    monkeypatch.setattr(decision_graph, "get_structured", lambda p, s, n: escalate if n == "decision_review" else {"explanation": "x"})
    rec = isolated_audit.get(decide().decision_id)
    assert rec.baseline_action == "route" and rec.final_action == "manual_review" and rec.changed_by_ai is True
    assert rec.reason_codes[0] == "AI_ESCALATION" and rec.llm["escalate_to_review"] is True


def test_tool_failure_is_audited_with_the_failing_call(isolated_audit, monkeypatch):
    import tools
    original = tools.TOOLS["provider_lookup"]
    monkeypatch.setitem(tools.TOOLS, "provider_lookup", tools.Tool("provider_lookup", "", original.input_model,
                                                                   lambda a: (_ for _ in ()).throw(ValueError("db down")), original.check_output))
    rec = isolated_audit.get(decide().decision_id)
    assert rec.final_action == "manual_review" and rec.reason_codes == ["TOOL_ERROR"]
    assert rec.tools_used[-1]["tool"] == "provider_lookup" and rec.tools_used[-1]["ok"] is False and any("tool failure" in n for n in rec.technical_notes)


# --- store: lookup, integrity, immutability ----------------------------------------------------------------------------------------
def test_unknown_id_raises_not_found(isolated_audit):
    with pytest.raises(AuditNotFound):
        isolated_audit.get("dec_missing")
    with pytest.raises(AuditNotFound):
        isolated_audit.verify("dec_missing")


def test_lookup_by_transaction_id_lists_every_decision_in_order(isolated_audit):
    first, second = decide().decision_id, decide().decision_id
    decide(transaction_id="other")
    assert isolated_audit.for_transaction("t-1") == [first, second] and isolated_audit.for_transaction("nope") == []


def test_integrity_check_detects_tampering(isolated_audit):
    r = decide()
    assert isolated_audit.verify(r.decision_id) is True
    with sqlite3.connect(isolated_audit.path) as db:
        db.execute("UPDATE audit SET record = replace(record, 'route', 'ROUTE') WHERE decision_id = ?", (r.decision_id,))
    assert isolated_audit.verify(r.decision_id) is False


def test_records_are_insert_only(isolated_audit):
    r = decide()
    with pytest.raises(sqlite3.IntegrityError):                                      # same id cannot be written twice
        isolated_audit.save(isolated_audit.get(r.decision_id))


def test_store_survives_reopening(isolated_audit):
    r = decide()
    assert AuditStore(isolated_audit.path).get(r.decision_id).transaction_id == "t-1"


def test_record_model_round_trips_through_json(isolated_audit):
    rec = isolated_audit.get(decide().decision_id)
    assert AuditRecord.model_validate_json(rec.model_dump_json()) == rec


# --- failure behaviour ---------------------------------------------------------------------------------------------------------------
def test_audit_failure_does_not_block_the_decision_but_is_flagged_and_logged(monkeypatch, caplog):
    class Broken:
        def save(self, record):
            raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(decision_graph, "audit_store", Broken())
    with caplog.at_level(logging.ERROR):
        r = decide()
    assert r.decision.action is Action.ROUTE and r.audit_recorded is False
    assert any("audit_failed" in rec.getMessage() and "disk full" in rec.getMessage() for rec in caplog.records)


# --- correlation with runtime logs ----------------------------------------------------------------------------------------------------
def test_runtime_logs_of_a_decision_carry_its_decision_id(isolated_audit):
    import io

    from observability import configure_logging
    original_stream = next(h.stream for h in logging.getLogger().handlers if getattr(h, "_app_handler", False))
    buffer = io.StringIO()
    configure_logging(stream=buffer, fmt="json")
    try:
        r = decide()
    finally:
        configure_logging(stream=original_stream)      # put the app's handler back on its ORIGINAL stream (never on a per-test one)
    lines = [json.loads(line) for line in buffer.getvalue().splitlines() if line.startswith("{")]
    tagged = [line for line in lines if line.get("decision_id") == r.decision_id]
    assert {"graph_node", "tool_call", "audit_recorded", "graph_done"} <= {line["event"] for line in tagged}


def test_decision_id_is_not_left_set_after_the_decision():
    from observability import decision_id_var
    decide()
    assert decision_id_var.get() == "-"


def test_new_decision_ids_look_right():
    ids = {new_decision_id() for _ in range(1000)}
    assert len(ids) == 1000 and all(i.startswith("dec_") and len(i) == 20 for i in ids)


# --- API -------------------------------------------------------------------------------------------------------------------------------
def test_decision_endpoint_returns_the_id_and_the_audit_endpoint_returns_the_record():
    body = client.post("/decision", json=ROUTINE).json()
    assert body["decision_id"].startswith("dec_") and body["audit_recorded"] is True
    audit_body = client.get(f"/decision/audit/{body['decision_id']}").json()
    assert audit_body["integrity_ok"] is True and audit_body["record"]["decision_id"] == body["decision_id"]
    assert audit_body["record"]["final_action"] == body["decision"]["action"]


def test_audit_endpoint_404_for_unknown_id():
    r = client.get("/decision/audit/dec_nope")
    assert r.status_code == 404 and "dec_nope" in r.json()["detail"]


def test_audit_lookup_by_transaction():
    ids = [client.post("/decision", json=ROUTINE).json()["decision_id"] for _ in range(2)]
    assert client.get("/decision/audit", params={"transaction_id": "t-1"}).json()["decision_ids"] == ids
    assert client.get("/decision/audit").status_code == 422                        # transaction_id is required


def test_audit_endpoints_require_the_api_key_when_configured(settings_override):
    settings_override(app_api_key="s3cret")
    assert client.get("/decision/audit/dec_x").status_code == 401
    assert client.get("/decision/audit/dec_x", headers={"X-API-Key": "s3cret"}).status_code == 404       # authenticated, just not found
    assert client.post("/decision", json=ROUTINE).status_code == 401


def test_audit_response_separates_business_explanation_from_technical_notes():
    body = client.post("/decision", json={**ROUTINE, "country": "ZZ"}).json()
    rec = client.get(f"/decision/audit/{body['decision_id']}").json()["record"]
    assert rec["business_explanation"].startswith("Sent to manual review") and rec["technical_notes"][0].startswith("fallback route")
