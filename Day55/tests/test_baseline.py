"""Day 31: risk score, eligibility, scoring, the baseline decision, the API endpoint and the explanation template."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import decision_engine
from data_loader import get_provider, load_providers
from decision_engine import decide_baseline, ineligible_reason, score_provider
from explanations import REASON_TEXT, template_explanation
from main import app
from risk import compute_risk
from schemas import Action, Decision, ReasonCode, Transaction

ROOT = Path(__file__).resolve().parent.parent
BASE = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 100.0, "currency": "USD", "country": "US",
        "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card",
        "customer_age_days": 400, "prior_chargebacks": 0}
client = TestClient(app)


def tx(**changes) -> Transaction:
    return Transaction(**{**BASE, **changes})


# --- risk ---------------------------------------------------------------------------------------------------------
def test_risk_is_bounded_and_explains_itself():
    r = compute_risk(tx())
    assert 0 <= r.score <= 1 and set(r.components) == {"country", "category", "customer", "amount", "chargebacks"}
    assert r.score == pytest.approx(sum(r.components.values()), abs=1e-3)


def test_risk_ordering_matches_intuition():
    safe = compute_risk(tx()).score
    assert compute_risk(tx(country="NG")).score > compute_risk(tx(country="IL")).score
    assert compute_risk(tx(merchant_category="gaming")).score > safe
    assert compute_risk(tx(customer_type="new", customer_age_days=2)).score > safe > compute_risk(tx(customer_type="vip")).score
    assert compute_risk(tx(prior_chargebacks=3)).score > safe
    assert compute_risk(tx(amount=100000)).score > safe


def test_amount_adjustment_is_capped_and_currency_aware():
    huge = compute_risk(tx(amount=1_000_000))
    assert huge.components["amount"] == 0.15
    # 216 ILS is ~60 USD, a typical grocery basket -> no amount penalty
    assert compute_risk(tx(currency="ILS", country="IL", amount=216)).components["amount"] == 0.0


def test_chargeback_effect_is_capped():
    assert compute_risk(tx(prior_chargebacks=100)).components["chargebacks"] == 0.30


def test_unknown_country_is_treated_as_risky_not_safe():
    assert compute_risk(tx(country="ZZ")).components["country"] == pytest.approx(0.45 * 0.40)


def test_many_chargebacks_add_a_reason_code():
    assert ReasonCode.PRIOR_CHARGEBACKS in compute_risk(tx(prior_chargebacks=2)).reason_codes
    assert not compute_risk(tx(prior_chargebacks=1)).reason_codes


# --- eligibility (hard constraints) ---------------------------------------------------------------------------------
@pytest.mark.parametrize("provider,changes,cause", [
    ("beta_bank", {"payment_method": "card", "country": "DE", "currency": "EUR"}, "method_not_supported"),
    ("beta_bank", {"payment_method": "bank_transfer"}, "country_not_supported"),
    ("epsilon_local_il", {"country": "US"}, "country_not_supported"),
    ("zeta_budget", {"currency": "ILS"}, "currency_not_supported"),
    ("zeta_budget", {"amount": 3500}, "amount_above_limit"),
    ("alpha_pay", {"amount": 25000}, "amount_above_limit"),
    ("alpha_pay", {}, None),
])
def test_ineligibility_causes(provider, changes, cause):
    assert ineligible_reason(get_provider(provider), tx(**changes), 0.1) == cause


def test_risk_tolerance_is_a_hard_limit():
    zeta = get_provider("zeta_budget")                     # tolerates up to 0.40
    assert ineligible_reason(zeta, tx(), 0.39) is None
    assert ineligible_reason(zeta, tx(), 0.41) == "risk_above_tolerance"


# --- scoring ---------------------------------------------------------------------------------------------------------
def test_cost_and_approval_estimates():
    alpha = get_provider("alpha_pay")
    c = score_provider(alpha, tx(amount=100.0), 0.0)
    assert c.expected_cost == pytest.approx(100 * 0.029 + 0.30) and c.expected_approval_probability == pytest.approx(0.93 * 0.999, abs=1e-4)


def test_higher_risk_lowers_approval_and_score():
    alpha = get_provider("alpha_pay")
    low, high = score_provider(alpha, tx(), 0.05), score_provider(alpha, tx(), 0.35)
    assert high.expected_approval_probability < low.expected_approval_probability and high.score < low.score


def test_cheaper_provider_wins_when_approval_is_similar():
    cheap, dear = get_provider("epsilon_local_il"), get_provider("delta_global")
    t = tx(country="IL", currency="ILS", amount=500)
    assert score_provider(cheap, t, 0.1).score > score_provider(dear, t, 0.1).score


# --- decisions ---------------------------------------------------------------------------------------------------------
def test_low_risk_payment_is_routed_with_reasons():
    r = decide_baseline(tx(country="IL", currency="ILS", amount=216))
    d = r.decision
    assert d.action is Action.ROUTE and d.selected_provider == "epsilon_local_il" and ReasonCode.LOW_RISK in d.reason_codes
    assert d.expected_cost > 0 and 0 < d.expected_approval_probability <= 1 and r.candidates[0].provider_id == d.selected_provider


def test_high_risk_is_declined():
    d = decide_baseline(tx(country="NG", merchant_category="digital_goods", customer_type="new", customer_age_days=1,
                           prior_chargebacks=2, amount=1800)).decision
    assert d.action is Action.DECLINE and d.reason_codes[0] is ReasonCode.HIGH_RISK and d.selected_provider is None
    assert ReasonCode.PRIOR_CHARGEBACKS in d.reason_codes


def test_medium_risk_goes_to_manual_review():
    d = decide_baseline(tx(country="NG", merchant_category="electronics", customer_type="new", customer_age_days=5,
                           prior_chargebacks=1)).decision
    assert d.action is Action.MANUAL_REVIEW and d.reason_codes[0] in (ReasonCode.MEDIUM_RISK, ReasonCode.HIGH_RISK)


def test_new_customer_large_amount_is_reviewed_even_if_risk_is_moderate():
    d = decide_baseline(tx(customer_type="new", customer_age_days=3, amount=2400, merchant_category="electronics")).decision
    assert d.action is Action.MANUAL_REVIEW and d.reason_codes[0] is ReasonCode.NEW_CUSTOMER_HIGH_AMOUNT


def test_no_eligible_provider_means_manual_review_not_a_crash(monkeypatch):
    monkeypatch.setattr(decision_engine, "load_providers", lambda: tuple(p for p in load_providers() if p.provider_id == "beta_bank"))
    r = decide_baseline(tx(country="DE", currency="EUR"))  # beta_bank only carries bank transfers; this is a card payment
    assert r.decision.action is Action.MANUAL_REVIEW and r.decision.reason_codes[0] is ReasonCode.NO_ELIGIBLE_PROVIDER
    assert r.rejected == {"beta_bank": "method_not_supported"}


def test_only_one_eligible_provider_gets_an_honest_reason():
    d = decide_baseline(tx(payment_method="bank_transfer", country="BR", currency="GBP", amount=640)).decision
    assert d.selected_provider == "delta_global" and ReasonCode.ONLY_ELIGIBLE_PROVIDER in d.reason_codes
    assert ReasonCode.CHEAPEST_ELIGIBLE not in d.reason_codes


def test_selected_provider_is_always_eligible_and_top_ranked():
    for e in json.loads((ROOT / "data" / "sample_events.json").read_text(encoding="utf8")):
        t = Transaction(**e)
        r = decide_baseline(t)
        if r.decision.action is Action.ROUTE:
            assert ineligible_reason(get_provider(r.decision.selected_provider), t, r.risk.score) is None
            assert [c.score for c in r.candidates] == sorted((c.score for c in r.candidates), reverse=True)


def test_thresholds_come_from_settings(settings_override):
    settings_override(risk_review=0.05)
    assert decide_baseline(tx()).decision.action is Action.MANUAL_REVIEW
    settings_override(risk_review=0.45, risk_decline=0.10)
    assert decide_baseline(tx(country="BR", merchant_category="gaming")).decision.action is Action.DECLINE


def test_decisions_are_deterministic():
    assert decide_baseline(tx()).decision == decide_baseline(tx()).decision


def test_decisions_always_satisfy_the_output_contract():
    from data_loader import iter_transactions
    for t in iter_transactions(limit=200):
        d = decide_baseline(t).decision
        assert isinstance(d, Decision) and d.reason_codes and (d.action is Action.ROUTE) == bool(d.selected_provider)


def test_decision_is_logged_with_its_inputs_and_outputs(caplog):
    import logging
    with caplog.at_level(logging.INFO):
        decide_baseline(tx())
    line = next(r for r in caplog.records if "decision_made" in r.getMessage()).getMessage()
    assert "mode=baseline" in line and "transaction_id=t-1" in line and "action=route" in line and "risk_score=" in line


# --- explanation template -----------------------------------------------------------------------------------------------
def test_every_reason_code_has_text():
    assert set(REASON_TEXT) == set(ReasonCode)


def test_template_mentions_action_provider_reasons_and_numbers():
    text = template_explanation(decide_baseline(tx(country="IL", currency="ILS", amount=216)).decision)
    assert text.startswith("Routed to epsilon_local_il because") and "risk score" in text and "Expected fee" in text


def test_template_for_non_routed_decisions():
    text = template_explanation(Decision(transaction_id="t", action=Action.DECLINE, reason_codes=[ReasonCode.HIGH_RISK], risk_score=0.9))
    assert text.startswith("Declined because") and "Expected fee" not in text


# --- API ---------------------------------------------------------------------------------------------------------------------
def test_baseline_endpoint_returns_decision_details_and_explanation():
    r = client.post("/decision/baseline", json=BASE)
    body = r.json()
    assert r.status_code == 200 and body["decision"]["action"] == "route" and body["decision"]["explanation"]
    assert body["risk"]["score"] == body["decision"]["risk_score"] and body["candidates"] and "rejected_providers" in body


def test_baseline_endpoint_rejects_invalid_input():
    assert client.post("/decision/baseline", json={**BASE, "amount": -5}).status_code == 422
