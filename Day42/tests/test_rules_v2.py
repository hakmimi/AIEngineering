"""Day 38: the three v2 pattern rules - they must catch the Day 37 blind spots AND leave ordinary payments alone."""
import json

import pytest

from data_loader import iter_transactions
from decision_engine import decide_baseline
from explanations import REASON_TEXT
from schemas import Action, ReasonCode, Transaction
from version import AGENT_VERSION, CHANGELOG

BASE = {"transaction_id": "t", "timestamp": "2026-01-05T09:12:00Z", "amount": 100, "currency": "USD", "country": "US",
        "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 500,
        "prior_chargebacks": 0}


def decide(**changes):
    return decide_baseline(Transaction(**{**BASE, **changes})).decision


# --- card testing ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("changes", [
    {"amount": 1, "merchant_category": "digital_goods", "customer_type": "new", "customer_age_days": 1},
    {"amount": 5, "merchant_category": "gaming", "customer_type": "new", "customer_age_days": 3},
    {"amount": 4, "currency": "EUR", "merchant_category": "gaming", "customer_type": "new", "customer_age_days": 2},         # ~4.3 USD
    {"amount": 3, "currency": "GBP", "merchant_category": "digital_goods", "customer_type": "new", "customer_age_days": 0, "payment_method": "wallet"},
])
def test_tiny_purchases_by_new_accounts_in_card_testing_categories_go_to_review(changes):
    d = decide(**changes)
    assert d.action is Action.MANUAL_REVIEW and d.reason_codes[0] is ReasonCode.CARD_TESTING_PATTERN


@pytest.mark.parametrize("changes", [
    {"amount": 1, "merchant_category": "digital_goods"},                                                                     # returning customer
    {"amount": 1, "merchant_category": "gaming", "customer_type": "vip", "customer_age_days": 900},
    {"amount": 1, "merchant_category": "groceries", "customer_type": "new", "customer_age_days": 1},                        # category not targeted
    {"amount": 20, "merchant_category": "digital_goods", "customer_type": "new", "customer_age_days": 10},                  # not tiny
    {"amount": 6, "merchant_category": "gaming", "customer_type": "new", "customer_age_days": 10, "currency": "USD"},       # just above the limit
])
def test_card_testing_rule_does_not_fire_on_ordinary_payments(changes):
    assert decide(**changes).reason_codes[0] is not ReasonCode.CARD_TESTING_PATTERN


# --- amount anomaly ------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("changes", [
    {"amount": 5000},                                                                # ~83x a typical grocery basket
    {"amount": 3000, "currency": "GBP"},                                             # ~62x
    {"amount": 45000, "currency": "EUR", "merchant_category": "utilities", "payment_method": "bank_transfer", "country": "DE"},
])
def test_amounts_far_above_the_category_norm_go_to_review(changes):
    d = decide(**changes)
    assert d.action is Action.MANUAL_REVIEW and d.reason_codes[0] is ReasonCode.AMOUNT_ANOMALY


@pytest.mark.parametrize("changes", [
    {"amount": 400}, {"amount": 1700},                                               # 7x and 28x - unusual but below the 30x line
    {"amount": 8000, "merchant_category": "luxury", "customer_type": "vip", "customer_age_days": 1200},    # 5x for luxury
    {"amount": 5200, "currency": "EUR", "country": "DE", "merchant_category": "travel", "customer_type": "vip", "customer_age_days": 900},
])
def test_large_but_plausible_amounts_are_not_anomalies(changes):
    assert decide(**changes).reason_codes[0] is not ReasonCode.AMOUNT_ANOMALY


def test_the_anomaly_threshold_is_configurable(settings_override):
    assert decide(amount=1700).action is Action.ROUTE
    settings_override(amount_anomaly_multiple=20)
    assert decide(amount=1700).reason_codes[0] is ReasonCode.AMOUNT_ANOMALY


# --- chargeback history ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("count", [3, 4, 5, 10])
def test_three_or_more_chargebacks_go_to_review_even_in_a_safe_country(count):
    d = decide(prior_chargebacks=count, amount=150)
    assert d.action in (Action.MANUAL_REVIEW, Action.DECLINE)
    if d.action is Action.MANUAL_REVIEW:
        assert d.reason_codes[0] is ReasonCode.PRIOR_CHARGEBACKS and d.reason_codes.count(ReasonCode.PRIOR_CHARGEBACKS) == 1


@pytest.mark.parametrize("count", [0, 1, 2])
def test_fewer_chargebacks_do_not_trigger_the_rule(count):
    assert decide(prior_chargebacks=count).action is Action.ROUTE


# --- interplay with the older rules ----------------------------------------------------------------------------------------------------
def test_high_risk_still_declines_before_any_pattern_rule():
    d = decide(country="NG", merchant_category="digital_goods", customer_type="new", customer_age_days=1, prior_chargebacks=3, amount=1800, payment_method="wallet")
    assert d.action is Action.DECLINE and d.reason_codes[0] is ReasonCode.HIGH_RISK


def test_pattern_rules_only_add_review_never_remove_it():
    """v2 must never turn a v1 review/decline into a route (checked on 500 synthetic transactions)."""
    import decision_engine
    for tx in iter_transactions(limit=500):
        d = decide_baseline(tx).decision
        if d.action is Action.ROUTE:
            assert decision_engine._pattern_reason(tx) is None and decision_engine.risk_rule_decision(tx, decide_baseline(tx).risk) is None


def test_the_synthetic_population_is_barely_affected():
    reviews = sum(decide_baseline(tx).decision.action is Action.MANUAL_REVIEW for tx in iter_transactions())
    assert 40 <= reviews <= 90                                                        # ~6 % of 1,000, up from ~5.6 %


def test_pattern_rules_run_without_provider_lookups():
    from tool_pipeline import decide_with_tools
    r = decide_with_tools(Transaction(**{**BASE, "amount": 5000}))
    assert [c["tool"] for c in r.trace.calls] == ["risk_lookup"] and r.decision.reason_codes[0] is ReasonCode.AMOUNT_ANOMALY


# --- versioning & wiring ------------------------------------------------------------------------------------------------------------------
def test_version_tag_and_changelog():
    assert AGENT_VERSION == "v3" and set(CHANGELOG) == {"v1", "v2", "v3"}


def test_decision_log_carries_the_agent_version(caplog):
    import logging
    with caplog.at_level(logging.INFO):
        decide()
    assert any("agent_version=v3" in r.getMessage() for r in caplog.records)


def test_new_reason_codes_have_explanation_text():
    assert {ReasonCode.CARD_TESTING_PATTERN, ReasonCode.AMOUNT_ANOMALY} <= set(REASON_TEXT)


def test_eval_dataset_contains_the_holdout_and_guard_cases():
    from evaluation import load_cases
    holdout = [c for c in load_cases() if c.category == "holdout"]
    assert len(holdout) >= 8 and sum(c.expected.acceptable_actions == [Action.ROUTE] for c in holdout) >= 4      # guards expect routing


def test_stored_v2_evaluation_has_no_regression_against_v1():
    from scripts.eval_compare import compare
    result = compare("v1", "v2")
    assert result["ai_regressed"] == [] and result["baseline_regressed"] == [] and result["versions"][1] == "v2"
    assert set(json.loads(json.dumps(result["ai_fixed"]))) == {"p01_card_testing_digital", "p02_card_testing_gaming", "p03_grocery_5000", "p04_four_chargebacks"}
