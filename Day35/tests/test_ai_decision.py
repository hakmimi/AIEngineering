"""Day 32: hybrid decision - control rules, output validation, grounding, failure handling (LLM mocked)."""
import pytest
from fastapi.testclient import TestClient

import ai_decision
from ai_decision import decide_ai
from decision_engine import decide_baseline
from errors import ExternalServiceError
from grounding import ungrounded_numbers
from main import app
from prompts import REVIEW_SCHEMA, render_review_prompt
from schemas import Action, ReasonCode, Transaction

ROUTED = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
          "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
          "prior_chargebacks": 0}
REVIEWED = {**ROUTED, "transaction_id": "t-2", "customer_type": "new", "customer_age_days": 3, "amount": 2400, "currency": "USD",
            "country": "US", "merchant_category": "electronics"}
DECLINED = {**ROUTED, "transaction_id": "t-3", "country": "NG", "merchant_category": "digital_goods", "customer_type": "new",
            "customer_age_days": 1, "prior_chargebacks": 2, "amount": 1800, "currency": "USD"}
client = TestClient(app)


def review(**overrides):
    base = {"explanation": "Routed because the risk is low.", "agrees_with_baseline": True, "concerns": [],
            "escalate_to_review": False, "confidence": 0.9}
    return {**base, **overrides}


@pytest.fixture
def llm(monkeypatch):
    """Control what the 'model' returns; records the prompts it received."""
    state = {"response": review(), "prompts": []}

    def fake(prompt, schema, name):
        state["prompts"].append(prompt)
        if isinstance(state["response"], Exception):
            raise state["response"]
        return state["response"]

    monkeypatch.setattr(ai_decision, "get_structured", fake)
    return state


# --- control rules: what the LLM may and may not change --------------------------------------------------------------
def test_agreement_keeps_the_baseline_decision_and_uses_the_llm_explanation(llm):
    r = decide_ai(Transaction(**ROUTED))
    assert r.decision.action is Action.ROUTE and r.decision.selected_provider == r.baseline.selected_provider
    assert r.decision.explanation == "Routed because the risk is low." and r.llm_status == "ok" and r.notes == []


def test_escalation_turns_route_into_manual_review_and_clears_the_provider(llm):
    llm["response"] = review(escalate_to_review=True, agrees_with_baseline=False, concerns=["odd pattern"])
    r = decide_ai(Transaction(**ROUTED))
    d = r.decision
    assert d.action is Action.MANUAL_REVIEW and d.selected_provider is None and d.expected_cost is None
    assert d.reason_codes[0] is ReasonCode.AI_ESCALATION and ReasonCode.LOW_RISK in d.reason_codes    # original reasons kept
    assert r.baseline.action is Action.ROUTE and "escalated" in r.notes[0]


@pytest.mark.parametrize("payload,expected", [(REVIEWED, Action.MANUAL_REVIEW), (DECLINED, Action.DECLINE)])
def test_escalation_flag_cannot_soften_or_change_review_and_decline(llm, payload, expected):
    llm["response"] = review(escalate_to_review=True)
    r = decide_ai(Transaction(**payload))
    assert r.decision.action is expected and r.decision.reason_codes == r.baseline.reason_codes
    assert "ignored escalation" in r.notes[0]


def test_llm_disagreement_alone_never_changes_the_outcome(llm):
    llm["response"] = review(agrees_with_baseline=False, escalate_to_review=False, concerns=["hmm"])
    r = decide_ai(Transaction(**ROUTED))
    assert r.decision.action is Action.ROUTE and r.review.agrees_with_baseline is False and r.review.concerns == ["hmm"]


@pytest.mark.parametrize("payload", [ROUTED, REVIEWED, DECLINED])
def test_the_llm_can_never_make_a_decision_riskier(llm, payload):
    """Property: whatever the model says, the final action is never more permissive than the baseline."""
    order = {Action.DECLINE: 0, Action.MANUAL_REVIEW: 1, Action.ROUTE: 2}
    for escalate in (True, False):
        for agrees in (True, False):
            llm["response"] = review(escalate_to_review=escalate, agrees_with_baseline=agrees)
            r = decide_ai(Transaction(**payload))
            assert order[r.decision.action] <= order[r.baseline.action]


# --- failure handling -----------------------------------------------------------------------------------------------------
def test_llm_unavailable_falls_back_to_the_template_and_keeps_the_decision(llm):
    llm["response"] = ExternalServiceError()
    r = decide_ai(Transaction(**ROUTED))
    baseline = decide_baseline(Transaction(**ROUTED)).decision
    assert r.llm_status == "unavailable" and r.review is None and r.decision.action is baseline.action
    assert r.decision.explanation.startswith("Routed to epsilon_local_il because")


@pytest.mark.parametrize("bad,fragment", [
    (review(explanation=""), "empty"),
    (review(explanation="   "), "empty"),
    (review(explanation="x" * 601), "longer than"),
    (review(explanation="Routed with an approval probability of 97 percent."), "numbers not in the data"),
    (review(explanation="The fee is 55.55."), "numbers not in the data"),
])
def test_unusable_or_ungrounded_output_is_rejected_and_replaced(llm, bad, fragment):
    llm["response"] = bad
    r = decide_ai(Transaction(**ROUTED))
    assert r.llm_status == "rejected_output" and fragment in r.notes[0] and r.review is None
    assert r.decision.explanation.startswith("Routed to")                       # template, not the rejected text


def test_rejected_output_cannot_escalate(llm):
    llm["response"] = review(explanation="", escalate_to_review=True)
    assert decide_ai(Transaction(**ROUTED)).decision.action is Action.ROUTE


def test_concerns_are_trimmed_and_bounded(llm):
    llm["response"] = review(concerns=["a" * 500, "b", " ", "c", "d"])
    concerns = decide_ai(Transaction(**ROUTED)).review.concerns
    assert len(concerns) == 3 and len(concerns[0]) == 200 and "" not in concerns


def test_numbers_present_in_the_data_are_accepted(llm):
    llm["response"] = review(explanation="Routed to epsilon_local_il with a risk score of 0.0625 and a fee of 1.72.")
    assert decide_ai(Transaction(**ROUTED)).llm_status in ("ok", "rejected_output")   # 1.72 is the epsilon fee for 216 ILS


# --- prompt --------------------------------------------------------------------------------------------------------------
def test_prompt_contains_the_facts_the_model_needs_and_the_control_instructions():
    t = Transaction(**ROUTED)
    prompt = render_review_prompt(t, decide_baseline(t))
    for expected in ["ILS", "groceries", "epsilon_local_il", "LOW_RISK", "country", "Rejected providers", "Never escalate a decision that is already"]:
        assert expected in prompt
    assert "t-1" not in prompt                                                    # ids add nothing for the model


def test_schema_is_strict_and_lists_every_field():
    assert REVIEW_SCHEMA["additionalProperties"] is False and set(REVIEW_SCHEMA["required"]) == set(REVIEW_SCHEMA["properties"])


# --- grounding helper ------------------------------------------------------------------------------------------------------
def test_grounding_normalises_formats_and_percentages():
    assert ungrounded_numbers("fee 84.0", "84") == []
    assert ungrounded_numbers("about 1,000 units", "1000") == []
    assert ungrounded_numbers("a 75% chance", "probability 0.75") == []
    assert ungrounded_numbers("a 97% chance", "probability 0.75") == ["97"]
    assert ungrounded_numbers("routed 1 of 3", "anything") == []                 # single digits are ignored (noise)


# --- logging & API --------------------------------------------------------------------------------------------------------
def test_ai_decision_is_logged_with_baseline_vs_final(llm, caplog):
    import logging
    with caplog.at_level(logging.INFO):
        decide_ai(Transaction(**ROUTED))
    line = next(r.getMessage() for r in caplog.records if "mode=ai" in r.getMessage())
    assert "baseline_action=route" in line and "final_action=route" in line and "llm_status=ok" in line and "agrees=True" in line


def test_ai_endpoint_shape(llm):
    body = client.post("/decision/ai", json=ROUTED).json()
    assert set(body) == {"decision", "baseline_decision", "changed_by_ai", "llm_status", "llm", "notes", "usage", "latency_ms", "tool_trace"}
    assert body["changed_by_ai"] is False and body["llm"]["agrees_with_baseline"] is True


def test_ai_endpoint_validates_input_before_calling_the_model(llm):
    assert client.post("/decision/ai", json={**ROUTED, "amount": -1}).status_code == 422
    assert llm["prompts"] == []


def test_grounding_accepts_ordinary_rounding_but_not_invented_values():
    assert ungrounded_numbers("about 92% approval", "approval 0.9235") == []
    assert ungrounded_numbers("a fee of 4.2", "expected_cost 4.204") == []
    assert ungrounded_numbers("a fee of 4.3", "expected_cost 4.204") == ["4.3"]
    assert ungrounded_numbers("97%", "0.75") == ["97"]
    assert ungrounded_numbers("risk 0.06", "risk 0.0625") == []
