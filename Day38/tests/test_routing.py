"""Day 35: input routing (fallback), uncertainty review, and how both behave in the graph."""
import pytest
from fastapi.testclient import TestClient

import ai_decision
import decision_graph
from decision_graph import run_decision_graph
from errors import ExternalServiceError
from main import app
from routing import BORDERLINE_MARGIN, FALLBACK, LOW_CONFIDENCE_BELOW, NORMAL, classify_input, uncertainty_signals
from schemas import Action, ReasonCode, Transaction

BASE = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
        "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
        "prior_chargebacks": 0}
# new customer just below the review threshold (risk 0.4437) - a routed but borderline decision
BORDERLINE = {**BASE, "transaction_id": "t-b", "country": "BR", "merchant_category": "gaming", "customer_type": "new", "customer_age_days": 10,
              "currency": "USD", "amount": 100}
GOOD = {"explanation": "Explained.", "agrees_with_baseline": True, "concerns": [], "escalate_to_review": False, "confidence": 0.9}
client = TestClient(app)


def tx(**c):
    return Transaction(**{**BASE, **c})


@pytest.fixture
def llm(monkeypatch):
    state = {"review": GOOD, "uncertainty": {"explanation": "Check the customer's recent activity."}, "calls": []}

    def fake(prompt, schema, name):
        state["calls"].append(name)
        payload = state["uncertainty"] if name == "uncertainty_explanation" else state["review"]
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(decision_graph, "get_structured", fake)
    monkeypatch.setattr(ai_decision, "get_structured", fake)
    return state


# --- classify_input: pure function ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("changes,code", [
    ({"country": "ZZ"}, ReasonCode.UNKNOWN_COUNTRY),
    ({"amount": 60000, "currency": "USD"}, ReasonCode.EXTREME_AMOUNT),
    ({"amount": 200000, "currency": "ILS"}, ReasonCode.EXTREME_AMOUNT),                      # 55k USD
    ({"customer_type": "returning", "customer_age_days": 2}, ReasonCode.INCONSISTENT_PROFILE),
    ({"customer_type": "vip", "customer_age_days": 100}, ReasonCode.INCONSISTENT_PROFILE),
])
def test_edge_cases_go_to_the_fallback_route(changes, code):
    choice = classify_input(tx(**changes))
    assert choice.route == FALLBACK and choice.reason_code is code and choice.explanation


@pytest.mark.parametrize("changes", [{}, {"amount": 49000, "currency": "USD"}, {"customer_type": "returning", "customer_age_days": 7},
                                     {"customer_type": "vip", "customer_age_days": 180}, {"customer_type": "new", "customer_age_days": 0}])
def test_normal_inputs_stay_on_the_normal_route(changes):
    assert classify_input(tx(**changes)).route == NORMAL


# --- uncertainty_signals: pure function ---------------------------------------------------------------------------------------------
def test_only_routed_decisions_can_be_uncertain():
    assert uncertainty_signals(tx(), Action.DECLINE, 0.9, False, 0.1) == []
    assert uncertainty_signals(tx(), Action.MANUAL_REVIEW, 0.5, False, 0.1) == []


def test_each_signal_fires_on_its_own():
    assert uncertainty_signals(tx(), Action.ROUTE, 0.1, False, 0.9) == ["llm_disagrees"]
    assert uncertainty_signals(tx(), Action.ROUTE, 0.1, True, LOW_CONFIDENCE_BELOW - 0.01) == ["llm_low_confidence"]
    assert uncertainty_signals(tx(customer_type="new", customer_age_days=5), Action.ROUTE, 0.42, True, 0.9) == ["borderline_risk_new_customer"]


def test_no_signal_for_confident_agreement_or_missing_review():
    assert uncertainty_signals(tx(), Action.ROUTE, 0.1, True, 0.9) == []
    assert uncertainty_signals(tx(), Action.ROUTE, 0.1, None, None) == []             # LLM unavailable: not an uncertainty signal


def test_borderline_needs_both_new_customer_and_closeness_to_the_threshold():
    new = tx(customer_type="new", customer_age_days=5)
    assert uncertainty_signals(new, Action.ROUTE, 0.44, True, 0.9) and not uncertainty_signals(new, Action.ROUTE, 0.44 - BORDERLINE_MARGIN, True, 0.9)
    assert not uncertainty_signals(tx(), Action.ROUTE, 0.44, True, 0.9)              # returning customer


# --- fallback route in the graph ------------------------------------------------------------------------------------------------------
def test_unknown_country_takes_the_fallback_path_without_tools_or_llm(llm):
    r = run_decision_graph(tx(country="ZZ"))
    assert r.graph_trace == ["input", "route_input", "fallback", "finalize"] and r.graph_route == "fallback"
    assert r.decision.action is Action.MANUAL_REVIEW and r.decision.reason_codes == [ReasonCode.UNKNOWN_COUNTRY]
    assert r.tool_trace == [] and llm["calls"] == [] and r.llm_status == "skipped" and "fallback route" in r.notes[0]
    assert r.decision.explanation.startswith("Sent to manual review because")


@pytest.mark.parametrize("changes,code", [({"amount": 60000, "currency": "USD"}, ReasonCode.EXTREME_AMOUNT),
                                          ({"customer_type": "vip", "customer_age_days": 30}, ReasonCode.INCONSISTENT_PROFILE)])
def test_other_edge_cases_use_their_own_reason_codes(llm, changes, code):
    assert run_decision_graph(tx(**changes)).decision.reason_codes == [code]


# --- uncertainty route in the graph ---------------------------------------------------------------------------------------------------
def test_llm_disagreement_sends_a_routed_decision_to_a_human(llm):
    llm["review"] = {**GOOD, "agrees_with_baseline": False, "concerns": ["odd spending pattern"]}
    r = run_decision_graph(tx())
    assert r.graph_route == "uncertain" and r.graph_route_reason == "llm_disagrees"
    assert r.graph_trace[-3:] == ["llm_explain", "uncertainty_review", "finalize"]
    d = r.decision
    assert d.action is Action.MANUAL_REVIEW and d.selected_provider is None and d.reason_codes[0] is ReasonCode.LOW_CONFIDENCE
    assert ReasonCode.LOW_RISK in d.reason_codes and d.explanation == "Check the customer's recent activity."
    assert llm["calls"] == ["decision_review", "uncertainty_explanation"] and r.baseline.action is Action.ROUTE


def test_low_confidence_also_escalates(llm):
    llm["review"] = {**GOOD, "confidence": 0.3}
    assert run_decision_graph(tx()).decision.reason_codes[0] is ReasonCode.LOW_CONFIDENCE


def test_borderline_new_customer_escalates_even_when_the_llm_agrees(llm):
    r = run_decision_graph(Transaction(**BORDERLINE))
    assert r.baseline.action is Action.ROUTE and r.graph_route_reason == "borderline_risk_new_customer"
    assert r.decision.action is Action.MANUAL_REVIEW


def test_uncertainty_explanation_falls_back_to_a_template(llm):
    llm["review"] = {**GOOD, "agrees_with_baseline": False}
    llm["uncertainty"] = ExternalServiceError()
    r = run_decision_graph(tx())
    assert r.decision.action is Action.MANUAL_REVIEW and "llm disagrees" in r.decision.explanation


def test_ungrounded_uncertainty_explanation_is_replaced(llm):
    llm["review"] = {**GOOD, "agrees_with_baseline": False}
    llm["uncertainty"] = {"explanation": "There is a 87% chance of fraud."}
    assert "87" not in run_decision_graph(tx()).decision.explanation


def test_llm_unavailable_is_not_uncertainty_by_itself(llm):
    llm["review"] = ExternalServiceError()
    r = run_decision_graph(tx())
    assert r.graph_route == "normal" and r.decision.action is Action.ROUTE and r.llm_status == "unavailable"


def test_already_safe_decisions_are_never_touched_by_uncertainty(llm):
    llm["review"] = {**GOOD, "agrees_with_baseline": False, "confidence": 0.1}
    r = run_decision_graph(tx(customer_type="new", customer_age_days=3, amount=2400, currency="USD", country="US",
                              merchant_category="electronics"))
    assert r.graph_route == "normal" and r.decision.reason_codes[0] is ReasonCode.NEW_CUSTOMER_HIGH_AMOUNT
    assert "uncertainty_review" not in r.graph_trace


def test_the_safety_routes_can_only_add_oversight():
    order = {Action.DECLINE: 0, Action.MANUAL_REVIEW: 1, Action.ROUTE: 2}
    from decision_engine import decide_baseline
    for payload in (BASE, BORDERLINE, {**BASE, "country": "ZZ"}):
        t = Transaction(**payload)
        for review in (GOOD, {**GOOD, "agrees_with_baseline": False}, {**GOOD, "confidence": 0.1}):
            import unittest.mock as mock
            with mock.patch.object(decision_graph, "get_structured", lambda p, s, n, r=review: r if n == "decision_review" else {"explanation": "x"}):
                assert order[run_decision_graph(t).decision.action] <= order[decide_baseline(t).decision.action]


# --- structure & API ---------------------------------------------------------------------------------------------------------------------
def test_graph_has_the_new_nodes_and_edges():
    g = decision_graph.decision_graph.get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    assert {"route_input", "fallback", "uncertainty_review"} <= set(g.nodes)
    assert {("route_input", "fallback"), ("route_input", "risk_tool"), ("llm_explain", "uncertainty_review"), ("llm_explain", "finalize"),
            ("fallback", "finalize"), ("uncertainty_review", "finalize")} <= edges


def test_endpoint_reports_the_route(llm):
    body = client.post("/decision", json={**BASE, "country": "ZZ"}).json()
    assert body["graph"]["route"] == "fallback" and "country 'ZZ'" in body["graph"]["route_reason"]
    assert client.post("/decision", json=BASE).json()["graph"]["route"] == "normal"
