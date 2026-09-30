"""Day 34: the LangGraph decision workflow - same decisions as the direct pipeline, explicit paths, safe failures."""
import pytest
from fastapi.testclient import TestClient

import ai_decision
import decision_graph
import tools
from ai_decision import decide_ai
from data_loader import iter_transactions
from decision_engine import decide_baseline
from decision_graph import decision_graph as graph
from decision_graph import run_decision_graph
from errors import ExternalServiceError
from main import app
from schemas import Action, ReasonCode, Transaction

BASE = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
        "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
        "prior_chargebacks": 0}
REVIEWED = {**BASE, "transaction_id": "t-2", "customer_type": "new", "customer_age_days": 3, "amount": 2400, "currency": "USD",
            "country": "US", "merchant_category": "electronics"}
DECLINED = {**BASE, "transaction_id": "t-3", "country": "NG", "merchant_category": "digital_goods", "customer_type": "new",
            "customer_age_days": 1, "prior_chargebacks": 2, "amount": 1800, "currency": "USD"}
NO_PROVIDER = {**BASE, "transaction_id": "t-4", "country": "DE", "currency": "EUR", "amount": 90000}
GOOD_REVIEW = {"explanation": "Explained.", "agrees_with_baseline": True, "concerns": [], "escalate_to_review": False, "confidence": 0.9}
client = TestClient(app)


@pytest.fixture
def llm(monkeypatch):
    state = {"response": GOOD_REVIEW, "calls": 0}

    def fake(prompt, schema, name):
        state["calls"] += 1
        if isinstance(state["response"], Exception):
            raise state["response"]
        return state["response"]

    monkeypatch.setattr(decision_graph, "get_structured", fake)
    monkeypatch.setattr(ai_decision, "get_structured", fake)
    return state


def broken_tool(monkeypatch, name):
    original = tools.TOOLS[name]

    def boom(_args):
        raise ValueError("db down")

    monkeypatch.setitem(tools.TOOLS, name, tools.Tool(name, "", original.input_model, boom, original.check_output))


# --- equivalence with the non-graph pipeline ------------------------------------------------------------------------------------
def test_graph_decisions_equal_the_direct_pipeline_on_many_transactions(llm):
    for tx in iter_transactions(limit=200):
        via_graph = run_decision_graph(tx)
        assert via_graph.baseline == decide_baseline(tx).decision, tx.transaction_id
        assert via_graph.decision == decide_ai(tx).decision, tx.transaction_id


# --- paths -------------------------------------------------------------------------------------------------------------------------
def test_routed_path_visits_every_tool_node(llm):
    r = run_decision_graph(Transaction(**BASE))
    assert r.graph_trace == ["input", "risk_tool", "rules", "provider_tool", "cost_tool", "select", "llm_explain", "finalize"]
    assert r.decision.action is Action.ROUTE and r.decision.explanation == "Explained." and set(r.graph_timings) == set(r.graph_trace)


@pytest.mark.parametrize("payload,action", [(REVIEWED, Action.MANUAL_REVIEW), (DECLINED, Action.DECLINE)])
def test_risk_rules_skip_the_provider_nodes(llm, payload, action):
    r = run_decision_graph(Transaction(**payload))
    assert r.graph_trace == ["input", "risk_tool", "rules", "llm_explain", "finalize"] and r.decision.action is action
    assert [c["tool"] for c in r.tool_trace] == ["risk_lookup"]


def test_no_eligible_provider_ends_in_manual_review(llm):
    r = run_decision_graph(Transaction(**NO_PROVIDER))
    assert r.decision.action is Action.MANUAL_REVIEW and r.decision.reason_codes[0] is ReasonCode.NO_ELIGIBLE_PROVIDER
    assert "select" in r.graph_trace


# --- state and control -------------------------------------------------------------------------------------------------------------
def test_escalation_is_applied_in_finalize_and_only_for_routed_decisions(llm):
    llm["response"] = {**GOOD_REVIEW, "escalate_to_review": True}
    routed = run_decision_graph(Transaction(**BASE))
    assert routed.decision.action is Action.MANUAL_REVIEW and routed.decision.reason_codes[0] is ReasonCode.AI_ESCALATION
    assert run_decision_graph(Transaction(**DECLINED)).decision.action is Action.DECLINE


@pytest.mark.parametrize("response,status", [(GOOD_REVIEW, "ok"), ({**GOOD_REVIEW, "explanation": "Fee is 99.99."}, "rejected_output")])
def test_llm_status_flows_through_the_state(llm, response, status):
    llm["response"] = response
    r = run_decision_graph(Transaction(**BASE))
    assert r.llm_status == status and r.decision.action is Action.ROUTE
    if status != "ok":
        assert r.decision.explanation.startswith("Routed to")           # template fallback


def test_llm_unavailable_keeps_the_decision(llm):
    llm["response"] = ExternalServiceError()
    r = run_decision_graph(Transaction(**BASE))
    assert r.llm_status == "unavailable" and r.decision.action is Action.ROUTE


# --- failures ------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("failing,expected_trace", [
    ("risk_lookup", ["input", "risk_tool", "tool_error", "finalize"]),
    ("provider_lookup", ["input", "risk_tool", "rules", "provider_tool", "tool_error", "finalize"]),
    ("cost_estimate", ["input", "risk_tool", "rules", "provider_tool", "cost_tool", "tool_error", "finalize"]),
])
def test_tool_failures_route_to_the_tool_error_node(monkeypatch, llm, failing, expected_trace):
    broken_tool(monkeypatch, failing)
    r = run_decision_graph(Transaction(**BASE))
    assert r.graph_trace == expected_trace and llm["calls"] == 0            # no LLM call when we lack the data
    assert r.decision.action is Action.MANUAL_REVIEW and r.decision.reason_codes == [ReasonCode.TOOL_ERROR]
    assert r.notes[0].startswith("tool failure") and failing in r.notes[0] and r.llm_status == "skipped"


# --- structure, logging, API -----------------------------------------------------------------------------------------------------------
def test_graph_structure():
    g = graph.get_graph()
    assert {"input", "risk_tool", "rules", "provider_tool", "cost_tool", "select", "llm_explain", "tool_error", "finalize"} <= set(g.nodes)
    edges = {(e.source, e.target) for e in g.edges}
    assert {("rules", "llm_explain"), ("rules", "provider_tool"), ("select", "llm_explain"), ("risk_tool", "tool_error")} <= edges


def test_graph_run_is_logged(llm, caplog):
    import logging
    with caplog.at_level(logging.INFO):
        run_decision_graph(Transaction(**BASE))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "graph_node node=risk_tool" in text and "graph_done transaction_id=t-1" in text


def test_endpoint_returns_decision_trace_and_timings(llm):
    body = client.post("/decision", json=BASE).json()
    assert body["decision"]["action"] == "route" and body["graph"]["trace"][0] == "input" and "llm_explain" in body["graph"]["timings_ms"]
    assert body["tool_trace"][0]["tool"] == "risk_lookup" and body["changed_by_ai"] is False


def test_endpoint_validates_input(llm):
    assert client.post("/decision", json={**BASE, "amount": 0}).status_code == 422 and llm["calls"] == 0
