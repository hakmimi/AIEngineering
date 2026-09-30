"""Day 36: the evaluation dataset, the scoring logic and the rubric - so the measuring stick itself is tested."""
import json
import subprocess
import sys

import pytest

import evaluation
from data_loader import get_provider
from evaluation import (
    Actual,
    EvalCase,
    Expected,
    actual_from_baseline,
    load_cases,
    load_rubric,
    score_case,
    score_explanation,
    summarize,
)
from routing import classify_input
from schemas import Action, Decision, ReasonCode, Transaction

TX = Transaction(transaction_id="t", timestamp="2026-01-05T09:12:00Z", amount=216, currency="ILS", country="IL", merchant_category="groceries",
                 customer_type="returning", payment_method="card", customer_age_days=400)


def case(actions, providers=None, route="normal", reasons=None):
    return EvalCase("c", "normal", "d", TX, Expected([Action(a) for a in actions], providers, route, reasons or []))


def actual(action="route", provider="epsilon_local_il", route="normal", reasons=("LOW_RISK",)):
    return Actual(Action(action), provider, route, list(reasons))


# --- dataset ---------------------------------------------------------------------------------------------------------------------
def test_dataset_loads_and_is_diverse():
    cases = load_cases()
    assert len(cases) >= 20 and len({c.id for c in cases}) == len(cases)
    assert {"normal", "risky", "edge", "uncertain"} <= {c.category for c in cases}
    for category in ("normal", "risky", "edge", "uncertain"):
        assert sum(c.category == category for c in cases) >= 2


def test_every_expected_provider_really_exists_and_could_carry_the_payment():
    from decision_engine import ineligible_reason
    for c in load_cases():
        for provider_id in c.expected.acceptable_providers or []:
            provider = get_provider(provider_id)
            assert provider.supported_methods and c.transaction.payment_method in provider.supported_methods, c.id
            assert c.transaction.amount <= provider.max_amount, c.id
            assert ineligible_reason(provider, c.transaction, 0.1) in (None, "risk_above_tolerance"), c.id


def test_fallback_cases_are_really_fallback_inputs_and_the_others_are_not():
    for c in load_cases():
        is_fallback = classify_input(c.transaction).route == "fallback"
        assert is_fallback == (c.expected.route == "fallback"), c.id


def test_expected_reason_codes_are_real_codes_and_expectations_are_consistent():
    for c in load_cases():
        for code in c.expected.must_include_reason_codes:
            ReasonCode(code)
        if c.expected.route in ("fallback", "uncertain"):
            assert c.expected.acceptable_actions == [Action.MANUAL_REVIEW], c.id      # the safety routes always end with a human
        if c.category == "normal":
            assert Action.ROUTE in c.expected.acceptable_actions, c.id


def test_loader_rejects_bad_datasets(tmp_path):
    good = json.loads(evaluation.CASES_PATH.read_text(encoding="utf8"))[0]
    for bad, message in [([good, good], "duplicate"),
                         ([{**good, "id": "x", "expected": {**good["expected"], "acceptable_actions": []}}], "no acceptable action"),
                         ([{**good, "id": "y", "expected": {"acceptable_actions": ["decline"], "acceptable_providers": ["alpha_pay"]}}], "providers expected")]:
        path = tmp_path / "cases.json"
        path.write_text(json.dumps(bad), encoding="utf8")
        with pytest.raises(ValueError, match=message):
            load_cases(path)
    path.write_text(json.dumps([{**good, "id": "z", "transaction": {**good["transaction"], "amount": -1}}]), encoding="utf8")
    with pytest.raises(Exception):
        load_cases(path)


def test_limit_takes_the_first_n():
    assert [c.id for c in load_cases(limit=3)] == [c.id for c in load_cases()][:3]


# --- scoring -----------------------------------------------------------------------------------------------------------------------
def test_perfect_result_passes():
    r = score_case(case(["route"], ["epsilon_local_il"], reasons=["LOW_RISK"]), actual())
    assert r.passed and r.error_type is None and r.provider_ok and r.details == []


def test_acceptable_alternatives_are_accepted():
    assert score_case(case(["route"], ["alpha_pay", "epsilon_local_il"]), actual(provider="alpha_pay")).passed
    assert score_case(case(["manual_review", "decline"]), actual(action="decline", provider=None)).passed


def test_wrong_provider_fails_but_is_not_an_action_error():
    r = score_case(case(["route"], ["alpha_pay"]), actual(provider="zeta_budget"))
    assert not r.passed and r.action_ok and r.provider_ok is False and r.error_type is None


def test_missing_reason_code_and_wrong_route_fail():
    assert not score_case(case(["route"], reasons=["PRIOR_CHARGEBACKS"]), actual()).passed
    assert not score_case(case(["manual_review"], route="fallback"), actual(action="manual_review", provider=None, route="normal")).passed


@pytest.mark.parametrize("expected,got,kind", [
    (["manual_review"], "route", "unsafe_error"),
    (["decline"], "manual_review", "unsafe_error"),
    (["decline"], "route", "unsafe_error"),
    (["route"], "manual_review", "over_cautious"),
    (["route"], "decline", "over_cautious"),
    (["manual_review"], "decline", "over_cautious"),
    (["route", "decline"], "manual_review", "wrong_action"),        # in between two acceptable answers
])
def test_error_direction_is_classified(expected, got, kind):
    provider = "alpha_pay" if got == "route" else None
    assert score_case(case(expected), actual(action=got, provider=provider)).error_type == kind


def test_provider_is_only_checked_when_routing():
    assert score_case(case(["route", "manual_review"], ["alpha_pay"]), actual(action="manual_review", provider=None)).provider_ok is None


def test_summary_aggregates_correctly():
    results = [score_case(case(["route"]), actual()), score_case(case(["manual_review"]), actual()), score_case(case(["route"]), actual(action="decline", provider=None))]
    s = summarize(results)
    assert s["cases"] == 3 and s["pass_rate"] == pytest.approx(0.333, abs=1e-3) and s["errors"] == {"unsafe_error": 1, "over_cautious": 1}


def test_baseline_actual_has_no_route_concept():
    d = Decision(transaction_id="t", action=Action.DECLINE, reason_codes=[ReasonCode.HIGH_RISK], risk_score=0.9)
    a = actual_from_baseline(d)
    assert a.route == "normal" and a.action is Action.DECLINE and a.reason_codes == ["HIGH_RISK"]


# --- explanation rubric ---------------------------------------------------------------------------------------------------------------
def routed_decision():
    return Decision(transaction_id="t", action=Action.ROUTE, selected_provider="epsilon_local_il", reason_codes=[ReasonCode.LOW_RISK, ReasonCode.CHEAPEST_ELIGIBLE],
                    risk_score=0.0625, expected_cost=4.2, expected_approval_probability=0.9235)


def test_rubric_file_defines_five_criteria_and_a_threshold():
    rubric = load_rubric()
    assert set(rubric["criteria"]) == {"states_action", "gives_correct_reason", "grounded", "business_language", "concise"} and rubric["pass_threshold"] == 8


def test_good_explanation_scores_full_marks():
    text = "Routed to epsilon_local_il because the transaction has a low risk score (0.06) and it is the cheapest eligible provider."
    s = score_explanation(text, routed_decision(), TX)
    assert s["total"] == 10 and s["passed"]


@pytest.mark.parametrize("text,criterion,expected", [
    ("Everything looks fine here.", "states_action", 0),
    ("Routed somewhere because of low risk.", "states_action", 1),                    # provider not named
    ("Routed to epsilon_local_il for reasons.", "gives_correct_reason", 0),
    ("Routed to epsilon_local_il because it is the cheapest option.", "gives_correct_reason", 1),   # only a secondary reason
    ("Routed to epsilon_local_il with a fee of 99.99 because of low risk.", "grounded", 0),
    ("Routed to epsilon_local_il because of LOW_RISK.", "business_language", 0),
    ('{"action": "route"} epsilon_local_il low risk', "business_language", 0),
    ("Routed to epsilon_local_il because low risk. " + "More words. " * 60, "concise", 0),
])
def test_each_criterion_can_fail_independently(text, criterion, expected):
    assert score_explanation(text, routed_decision(), TX)[criterion] == expected


def test_empty_explanation_scores_zero():
    assert score_explanation("", routed_decision(), TX)["total"] == 0 and score_explanation(None, routed_decision(), TX)["passed"] is False


def test_template_explanations_pass_the_rubric_for_every_sample_event():
    from decision_engine import decide_baseline
    from explanations import template_explanation
    events = json.loads((evaluation.settings.data_dir / "sample_events.json").read_text(encoding="utf8"))
    for e in events:
        t = Transaction(**e)
        d = decide_baseline(t).decision
        assert score_explanation(template_explanation(d), d, t)["passed"], e["transaction_id"]


# --- runner ---------------------------------------------------------------------------------------------------------------------------------
def test_runner_cli_runs_the_first_cases_in_baseline_mode(tmp_path):
    out = subprocess.run([sys.executable, "-m", "scripts.eval_decisions", "run", "pytest_tmp", "--mode", "baseline", "--limit", "3"],
                         capture_output=True, text=True, cwd=str(evaluation.settings.base_dir), timeout=120)
    assert out.returncode == 0 and "PASS n01_il_grocery_card" in out.stdout and '"cases": 3' in out.stdout
    (evaluation.settings.data_dir / "eval" / "decisions_pytest_tmp.json").unlink()
