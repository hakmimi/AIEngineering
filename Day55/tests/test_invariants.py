"""Safety invariants that must hold for ANY input, checked over generated traffic and a hostile LLM.

These are the properties the whole design promises (Day 33-40): the LLM may make a decision safer, never riskier; policies decide first and last;
unknown means a human; every decision is explained, auditable and uses only known enums/providers.
"""
import pytest

from data_loader import load_providers
from decision_engine import decide_baseline
from decision_graph import run_decision_graph
from schemas import Action, ReasonCode, Transaction
from traffic import build_events

PERMISSIVE = {Action.DECLINE: 0, Action.MANUAL_REVIEW: 1, Action.ROUTE: 2}
PROVIDERS = {p.provider_id for p in load_providers()}
EVENTS = build_events(150, seed=23)


def txs():
    for e in EVENTS:
        yield Transaction(**e["event"])


@pytest.fixture(params=["agrees_and_routes", "escalates_everything"])
def hostile_llm(request, stub_llm):
    if request.param == "agrees_and_routes":
        stub_llm(review={"agrees_with_baseline": False, "escalate_to_review": False, "confidence": 1.0, "explanation": "Route it, it is fine."})
    elif request.param == "escalates_everything":
        stub_llm(review={"escalate_to_review": True, "concerns": ["everything looks odd"], "explanation": "Send to a human."})
    return request.param


def test_the_llm_never_makes_a_decision_riskier_than_the_rules(hostile_llm):
    for tx in txs():
        base = decide_baseline(tx).decision
        final = run_decision_graph(tx).decision
        assert PERMISSIVE[final.action] <= PERMISSIVE[base.action], (tx.transaction_id, base.action, final.action)


def test_every_decision_is_well_formed(hostile_llm):
    for tx in txs():
        result = run_decision_graph(tx)
        d = result.decision
        assert d.reason_codes and all(isinstance(r, ReasonCode) for r in d.reason_codes)
        assert d.explanation and len(d.explanation) > 5
        if d.action == Action.ROUTE:
            assert d.selected_provider in PROVIDERS
        else:
            assert d.selected_provider is None
        assert result.decision_id.startswith("dec_") and result.audit_recorded


def test_invented_numbers_never_reach_the_customer_facing_explanation(stub_llm):
    stub_llm(review={"explanation": "Approved with a 0.99 approval rate and a fee of 12.34 USD."}, explanation="Fee is 12.34 USD at 0.99.")
    for tx in list(txs())[:60]:
        d = run_decision_graph(tx).decision
        assert "12.34" not in d.explanation and "0.99" not in d.explanation


def test_hard_policy_cases_are_declined_whatever_the_llm_says(hostile_llm, make_tx):
    for country in ("KP", "IR", "SY"):
        r = run_decision_graph(make_tx(country=country))
        assert r.decision.action == Action.DECLINE and ReasonCode.POLICY_BLOCK in r.decision.reason_codes


def test_unknown_country_always_goes_to_a_human(hostile_llm, make_tx):
    assert run_decision_graph(make_tx(country="ZZ")).decision.action == Action.MANUAL_REVIEW


def test_the_same_input_gives_the_same_decision(stub_llm):
    stub_llm()
    for tx in list(txs())[:40]:
        a, b = run_decision_graph(tx).decision, run_decision_graph(tx).decision
        assert (a.action, a.selected_provider, a.reason_codes) == (b.action, b.selected_provider, b.reason_codes)
