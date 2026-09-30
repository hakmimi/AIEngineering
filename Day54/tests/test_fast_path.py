"""Day 39: the fast path - when the LLM is skipped, that it never changes a decision, and the latency/cost bookkeeping."""
import pytest
from fastapi.testclient import TestClient

import ai_decision
import decision_graph
from data_loader import iter_transactions
from decision_engine import decide_baseline
from decision_graph import run_decision_graph
from fast_path import evaluate_fast_path
from main import app
from schemas import Action, Transaction

ROUTINE = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
           "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
           "prior_chargebacks": 0}
GOOD_REVIEW = {"explanation": "Explained.", "agrees_with_baseline": True, "concerns": [], "escalate_to_review": False, "confidence": 0.9}
client = TestClient(app)


@pytest.fixture(autouse=True)
def fast_path_on(settings_override):
    settings_override(fast_path_enabled=True)


@pytest.fixture
def llm(monkeypatch):
    state = {"calls": 0}

    def fake(prompt, schema, name):
        state["calls"] += 1
        return GOOD_REVIEW if name == "decision_review" else {"explanation": "Check it."}

    monkeypatch.setattr(decision_graph, "get_structured", fake)
    monkeypatch.setattr(ai_decision, "get_structured", fake)
    return state


def verdict(**changes):
    tx = Transaction(**{**ROUTINE, **changes})
    return evaluate_fast_path(tx, decide_baseline(tx))


# --- the rule ---------------------------------------------------------------------------------------------------------------------
def test_routine_low_risk_payment_is_fast():
    v = verdict()
    assert v.fast and v.reason == "routine_low_risk"


@pytest.mark.parametrize("changes,reason", [
    ({"country": "NG", "merchant_category": "digital_goods", "customer_type": "new", "customer_age_days": 1, "prior_chargebacks": 2,
      "amount": 1800, "currency": "USD", "payment_method": "wallet"}, "clear_decline"),
])
def test_clear_declines_are_fast(changes, reason):
    v = verdict(**changes)
    assert v.fast and v.reason == reason


@pytest.mark.parametrize("changes,reason", [
    ({"prior_chargebacks": 1}, "chargeback_history"),
    ({"country": "BR", "merchant_category": "electronics", "amount": 900, "currency": "USD"}, "risk_above_fast_path_limit"),
    ({"customer_type": "new", "customer_age_days": 3, "amount": 2400, "currency": "USD", "country": "US", "merchant_category": "electronics"},
     "human_will_read_it"),                                                                           # manual review: a person reads the text
])
def test_cases_that_may_benefit_from_a_second_opinion_are_not_fast(changes, reason):
    v = verdict(**changes)
    assert not v.fast and v.reason == reason


@pytest.mark.parametrize("changes,reason", [
    ({"customer_type": "new", "customer_age_days": 20, "amount": 100, "currency": "USD", "country": "US"}, "new_customer"),
    ({"amount": 2500, "currency": "ILS"}, "unusual_amount"),                                        # ~700 USD groceries ~ 11x typical
])
def test_independent_safeguards_hold_even_when_the_risk_limit_is_relaxed(settings_override, changes, reason):
    """New customers and unusual amounts are normally kept off the fast path by the risk limit already; these are the backstops."""
    settings_override(fast_path_max_risk=0.6)
    v = verdict(**changes)
    assert not v.fast and v.reason == reason


def test_switch_disables_the_fast_path(settings_override):
    settings_override(fast_path_enabled=False)
    assert verdict().reason == "disabled" and not verdict().fast


def test_thresholds_are_configurable(settings_override):
    assert not verdict(country="BR", currency="USD", amount=100).fast
    settings_override(fast_path_max_risk=0.5)
    assert verdict(country="BR", currency="USD", amount=100).fast


# --- in the graph -------------------------------------------------------------------------------------------------------------------
def test_fast_path_skips_the_llm_completely(llm):
    r = run_decision_graph(Transaction(**ROUTINE))
    assert llm["calls"] == 0 and r.llm_status == "skipped_fast_path" and r.fast_path == "routine_low_risk"
    assert r.graph_trace == ["input", "policy_gate", "route_input", "risk_tool", "rules", "provider_tool", "cost_tool", "select", "fast_explain", "finalize", "constraint_guard"]
    assert r.decision.action is Action.ROUTE and r.decision.explanation.startswith("Routed to epsilon_local_il because")
    assert r.usage["llm_calls"] == 0 and r.usage["estimated_cost_usd"] == 0
    assert any("fast path" in n for n in r.notes)


def test_clear_decline_takes_the_fast_path_from_the_rules_node(llm):
    r = run_decision_graph(Transaction(**{**ROUTINE, "country": "NG", "merchant_category": "digital_goods", "customer_type": "new",
                                          "customer_age_days": 1, "prior_chargebacks": 2, "amount": 1800, "currency": "USD"}))
    assert r.decision.action is Action.DECLINE and llm["calls"] == 0 and r.graph_trace[-3:] == ["fast_explain", "finalize", "constraint_guard"]


def test_non_fast_cases_still_get_the_llm(llm):
    r = run_decision_graph(Transaction(**{**ROUTINE, "prior_chargebacks": 1}))
    assert llm["calls"] == 1 and r.llm_status == "ok" and r.fast_path is None and "llm_explain" in r.graph_trace


def test_fast_path_never_changes_a_decision(llm):
    """Decisions with and without the fast path must be identical on 300 transactions (the LLM mock never escalates)."""
    from config import settings
    for tx in iter_transactions(limit=300):
        object.__setattr__(settings, "fast_path_enabled", True)
        fast = run_decision_graph(tx).decision
        object.__setattr__(settings, "fast_path_enabled", False)
        slow = run_decision_graph(tx).decision
        assert (fast.action, fast.selected_provider, fast.reason_codes) == (slow.action, slow.selected_provider, slow.reason_codes), tx.transaction_id


def test_fast_path_reduces_llm_calls_on_realistic_traffic(llm):
    for tx in iter_transactions(limit=200):
        run_decision_graph(tx)
    with_fast = llm["calls"]
    llm["calls"] = 0
    object.__setattr__(decision_graph.evaluate_fast_path.__globals__["settings"], "fast_path_enabled", False)
    for tx in iter_transactions(limit=200):
        run_decision_graph(tx)
    assert with_fast < llm["calls"] and with_fast > 0.4 * llm["calls"]          # a real saving, but not everything is skipped


# --- latency & API ------------------------------------------------------------------------------------------------------------------
def test_fast_path_is_reported_in_the_api_and_has_no_llm_time(llm):
    body = client.post("/decision", json=ROUTINE).json()
    assert body["fast_path"] == "routine_low_risk" and body["llm_status"] == "skipped_fast_path"
    assert "llm_explain" not in body["graph"]["timings_ms"] and "fast_explain" in body["graph"]["timings_ms"]
    assert body["usage"]["llm_calls"] == 0 and body["latency_ms"] < 500


def test_baseline_endpoint_reports_its_latency():
    body = client.post("/decision/baseline", json=ROUTINE).json()
    assert 0 <= body["latency_ms"] < 100 and body["decision"]["action"] == "route"


def test_decision_log_contains_fast_path_and_latency(llm, caplog):
    import logging
    with caplog.at_level(logging.INFO):
        run_decision_graph(Transaction(**ROUTINE))
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "graph_fast_path transaction_id=t-1 reason=routine_low_risk" in text and "fast_path=routine_low_risk" in text and "latency_ms=" in text
