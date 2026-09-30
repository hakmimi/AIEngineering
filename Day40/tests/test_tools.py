"""Day 33: tool contracts, tool-backed decisions (must equal the baseline), failure handling, traces."""
import pytest
from fastapi.testclient import TestClient

import ai_decision
import tool_pipeline
import tools
from ai_decision import decide_ai
from data_loader import iter_transactions
from decision_engine import decide_baseline
from main import app
from prompts import render_review_prompt
from schemas import Action, ReasonCode, Transaction
from tool_pipeline import decide_with_tools
from tools import ToolTrace, execute_tool

BASE = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
        "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
        "prior_chargebacks": 0}
client = TestClient(app)
GOOD_REVIEW = {"explanation": "Routed because the risk is low.", "agrees_with_baseline": True, "concerns": [],
               "escalate_to_review": False, "confidence": 0.9}


def raising(exc):
    def fn(_args):
        raise exc
    return fn


# --- each tool ----------------------------------------------------------------------------------------------------------
def test_risk_lookup_matches_the_engines_own_risk():
    out = execute_tool("risk_lookup", {"country": "NG", "merchant_category": "gaming", "customer_type": "new", "amount": 500,
                                       "currency": "USD", "prior_chargebacks": 1}).output
    tx = Transaction(**{**BASE, "country": "NG", "merchant_category": "gaming", "customer_type": "new", "customer_age_days": 2,
                        "amount": 500, "currency": "USD", "prior_chargebacks": 1})
    assert out["risk_score"] == decide_baseline(tx).risk.score and out["country_known"] is True
    assert set(out["components"]) == {"country", "category", "customer", "amount", "chargebacks"}


def test_risk_lookup_flags_unknown_countries():
    out = execute_tool("risk_lookup", {"country": "ZZ", "merchant_category": "groceries", "customer_type": "returning",
                                       "amount": 10, "currency": "USD"}).output
    assert out["country_known"] is False


def test_provider_lookup_lists_eligible_and_rejected_with_causes():
    out = execute_tool("provider_lookup", {"country": "IL", "currency": "ILS", "payment_method": "card", "amount": 216, "risk": 0.06}).output
    assert set(out["eligible"]) == {"alpha_pay", "gamma_wallet", "delta_global", "epsilon_local_il"}
    assert out["rejected"] == {"beta_bank": "method_not_supported", "zeta_budget": "country_not_supported"}


def test_provider_lookup_applies_risk_tolerance():
    low = execute_tool("provider_lookup", {"country": "US", "currency": "USD", "payment_method": "card", "amount": 100, "risk": 0.1}).output
    high = execute_tool("provider_lookup", {"country": "US", "currency": "USD", "payment_method": "card", "amount": 100, "risk": 0.6}).output
    assert "zeta_budget" in low["eligible"] and high["rejected"]["zeta_budget"] == "risk_above_tolerance"


def test_cost_estimate_arithmetic():
    out = execute_tool("cost_estimate", {"provider_id": "alpha_pay", "amount": 100, "risk": 0.0}).output
    assert out["expected_cost"] == pytest.approx(3.2) and out["expected_approval_probability"] == pytest.approx(0.9291, abs=1e-4)


# --- validation and error handling --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,args,fragment", [
    ("risk_lookup", {}, "invalid arguments"),
    ("risk_lookup", {"country": "IL", "merchant_category": "weapons", "customer_type": "new", "amount": 1, "currency": "USD"}, "merchant_category"),
    ("provider_lookup", {"country": "IL", "currency": "ILS", "payment_method": "card", "amount": 10, "risk": 1.5}, "risk"),
    ("cost_estimate", {"provider_id": "alpha_pay", "amount": -5, "risk": 0.1}, "amount"),
    ("cost_estimate", {"provider_id": "nope", "amount": 5, "risk": 0.1}, "unknown provider"),
    ("teleport", {}, "unknown tool"),
])
def test_bad_calls_fail_safely(name, args, fragment):
    result = execute_tool(name, args)
    assert not result.ok and fragment in result.error and result.output is None


def test_output_contracts_reject_garbage(monkeypatch):
    garbage = {"risk_score": 7.0, "components": {}, "country_known": True, "reason_codes": []}
    bad = tools.Tool("risk_lookup", "x", tools.RiskLookupInput, lambda a: garbage, tools._check_risk)
    monkeypatch.setitem(tools.TOOLS, "risk_lookup", bad)
    result = execute_tool("risk_lookup", {"country": "IL", "merchant_category": "groceries", "customer_type": "new", "amount": 1, "currency": "USD"})
    assert not result.ok and "out of range" in result.error


def test_trace_records_every_call_including_failures():
    trace = ToolTrace()
    execute_tool("cost_estimate", {"provider_id": "alpha_pay", "amount": 100, "risk": 0.1}, trace)
    execute_tool("cost_estimate", {"provider_id": "nope", "amount": 100, "risk": 0.1}, trace)
    assert [(c["tool"], c["ok"]) for c in trace.calls] == [("cost_estimate", True), ("cost_estimate", False)]
    assert all(c["ms"] >= 0 for c in trace.calls) and trace.for_prompt()[1]["result"] == {"error": "unknown provider 'nope'"}


# --- tool-backed decisions ---------------------------------------------------------------------------------------------------------
def test_tool_pipeline_equals_the_direct_baseline_on_many_transactions():
    """The most important test of the day: fetching data through tools must not change a single decision."""
    for tx in iter_transactions(limit=300):
        via_tools = decide_with_tools(tx)
        direct = decide_baseline(tx)
        assert via_tools.decision == direct.decision, tx.transaction_id
        assert via_tools.baseline.rejected == direct.rejected
        assert [c.provider_id for c in via_tools.baseline.candidates] == [c.provider_id for c in direct.candidates]


def test_trace_order_for_a_routed_decision():
    result = decide_with_tools(Transaction(**BASE))
    names = [c["tool"] for c in result.trace.calls]
    assert names[0] == "risk_lookup" and names[1] == "provider_lookup" and set(names[2:]) == {"cost_estimate"}
    assert len(names) == 2 + len(result.baseline.candidates)
    assert all(c["ok"] for c in result.trace.calls)


def test_risk_rules_short_circuit_before_provider_tools():
    risky = {**BASE, "country": "NG", "merchant_category": "digital_goods", "customer_type": "new", "customer_age_days": 1,
             "prior_chargebacks": 2, "amount": 1800, "currency": "USD"}
    declined = decide_with_tools(Transaction(**risky))
    assert declined.decision.action is Action.DECLINE and [c["tool"] for c in declined.trace.calls] == ["risk_lookup"]


@pytest.mark.parametrize("failing", ["risk_lookup", "provider_lookup", "cost_estimate"])
def test_a_failing_tool_becomes_a_manual_review_not_an_error(monkeypatch, failing):
    original = tools.TOOLS[failing]
    broken = tools.Tool(failing, original.description, original.input_model, raising(ValueError("db down")), original.check_output)
    monkeypatch.setitem(tools.TOOLS, failing, broken)
    result = decide_with_tools(Transaction(**BASE))
    assert result.decision.action is Action.MANUAL_REVIEW and result.decision.reason_codes == [ReasonCode.TOOL_ERROR]
    assert result.tool_failure and failing in result.tool_failure and result.decision.risk_score == 0.5
    assert result.trace.calls[-1]["ok"] is False


# --- LLM sees the tool results ----------------------------------------------------------------------------------------------------------
def test_prompt_includes_the_tool_trace():
    tx = Transaction(**BASE)
    tooled = decide_with_tools(tx)
    prompt = render_review_prompt(tx, tooled.baseline, tooled.trace)
    assert "Tool results" in prompt and '"tool": "risk_lookup"' in prompt and '"tool": "cost_estimate"' in prompt
    assert "epsilon_local_il" in prompt and "base your explanation on these" in prompt


def test_ai_decision_uses_tools_and_returns_the_trace(monkeypatch):
    seen = {}
    monkeypatch.setattr(ai_decision, "get_structured", lambda p, s, n: seen.update(prompt=p) or GOOD_REVIEW)
    result = decide_ai(Transaction(**BASE))
    assert [c["tool"] for c in result.tool_trace][:2] == ["risk_lookup", "provider_lookup"] and "Tool results" in seen["prompt"]
    assert result.to_dict()["tool_trace"] == result.tool_trace


def test_ai_decision_survives_a_tool_failure(monkeypatch):
    original = tools.TOOLS["provider_lookup"]
    broken = tools.Tool("provider_lookup", "", original.input_model, raising(ValueError("down")), original.check_output)
    monkeypatch.setitem(tools.TOOLS, "provider_lookup", broken)
    monkeypatch.setattr(ai_decision, "get_structured", lambda p, s, n: {**GOOD_REVIEW, "explanation": "A person will decide."})
    result = decide_ai(Transaction(**BASE))
    assert result.decision.action is Action.MANUAL_REVIEW and result.notes[0].startswith("tool failure")


def test_tool_grounding_accepts_numbers_from_tool_results(monkeypatch):
    monkeypatch.setattr(ai_decision, "get_structured", lambda p, s, n: {**GOOD_REVIEW, "explanation": "The fee is 4.2 with 92% expected approval."})
    assert decide_ai(Transaction(**BASE)).llm_status == "ok"


# --- API ---------------------------------------------------------------------------------------------------------------------------------
def test_tools_endpoint_returns_decision_and_trace():
    body = client.post("/decision/tools", json=BASE).json()
    assert body["decision"]["action"] == "route" and body["tool_trace"][0]["tool"] == "risk_lookup" and body["tool_failure"] is None
    direct = client.post("/decision/baseline", json=BASE).json()
    assert body["decision"] == direct["decision"]


def test_tool_module_exposes_the_expected_tools():
    assert set(tools.TOOLS) == {"risk_lookup", "provider_lookup", "cost_estimate"} and tool_pipeline.UNKNOWN_RISK_SCORE == 0.5
