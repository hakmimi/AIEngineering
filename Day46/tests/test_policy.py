"""Day 41: policy constraints - the table, each rule kind, the gate before the decision, the guard after it, and the API format."""
import json
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import ai_decision
import decision_graph
import policy
from data_loader import get_provider
from decision_graph import run_decision_graph
from errors import DataStoreError
from main import app
from policy import Policy, Violation, check_policies, load_policies, policy_summary, strictest
from prompts import render_review_prompt
from schemas import Action, ReasonCode, Transaction

BASE = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 100, "currency": "USD", "country": "US",
        "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
        "prior_chargebacks": 0}
client = TestClient(app)


def tx(**changes):
    return Transaction(**{**BASE, **changes})


@pytest.fixture(autouse=True)
def llm(monkeypatch):
    calls = []

    def fake(prompt, schema, name):
        calls.append(name)
        return {"explanation": "Explained.", "agrees_with_baseline": True, "concerns": [], "escalate_to_review": False, "confidence": 0.9}

    monkeypatch.setattr(decision_graph, "get_structured", fake)
    monkeypatch.setattr(ai_decision, "get_structured", fake)
    return calls


# --- the table ---------------------------------------------------------------------------------------------------------------------
def test_shipped_policy_table_is_valid_and_readable():
    policies = load_policies()
    assert {p.id for p in policies} == {"P1_SANCTIONED_COUNTRY", "P2_AMOUNT_LIMIT_BY_CUSTOMER", "P3_WALLET_LIMIT", "P4_NO_GAMING_BY_BANK_TRANSFER"}
    assert all(p.action in (Action.MANUAL_REVIEW, Action.DECLINE) for p in policies)


@pytest.mark.parametrize("bad", [
    {"id": "P9_X", "kind": "blocked_country", "action": "route", "description": "routing is not a restriction", "params": {"countries": ["XX"]}},
    {"id": "bad id", "kind": "blocked_country", "action": "decline", "description": "id must follow the pattern", "params": {"countries": ["XX"]}},
    {"id": "P9_X", "kind": "blocked_country", "action": "decline", "description": "missing countries param here", "params": {}},
    {"id": "P9_X", "kind": "max_amount_by_customer", "action": "manual_review", "description": "needs all three customer types", "params": {"new": 1}},
    {"id": "P9_X", "kind": "max_amount_by_method", "action": "manual_review", "description": "limits must be positive numbers", "params": {"wallet": 0}},
    {"id": "P9_X", "kind": "forbidden_combination", "action": "decline", "description": "one field is not a combination", "params": {"payment_method": "card"}},
    {"id": "P9_X", "kind": "unknown_kind", "action": "decline", "description": "the kind must be a supported one", "params": {}},
])
def test_invalid_policies_are_rejected(bad):
    with pytest.raises(ValidationError):
        Policy(**bad)


def test_loader_rejects_duplicates_missing_and_corrupt_files(tmp_path, monkeypatch):
    p = load_policies()[0].model_dump(mode="json")
    for content, message in [(json.dumps([p, p]), "duplicate"), ("{oops", "not valid JSON")]:
        path = tmp_path / "p.json"
        path.write_text(content, encoding="utf8")
        monkeypatch.setattr(policy, "POLICIES_PATH", path)
        load_policies.cache_clear()
        with pytest.raises(DataStoreError, match=message):
            load_policies()
    monkeypatch.setattr(policy, "POLICIES_PATH", tmp_path / "missing.json")
    load_policies.cache_clear()
    with pytest.raises(DataStoreError, match="not found"):
        load_policies()
    load_policies.cache_clear()


# --- each kind of rule --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("country", ["KP", "IR", "SY", "CU"])
def test_sanctioned_countries_are_declined(country):
    v = check_policies(tx(country=country))
    assert [x.policy_id for x in v] == ["P1_SANCTIONED_COUNTRY"] and strictest(v) is Action.DECLINE


@pytest.mark.parametrize("changes,violated", [
    ({"customer_type": "new", "customer_age_days": 5, "amount": 5001}, True), ({"customer_type": "new", "customer_age_days": 5, "amount": 5000}, False),
    ({"amount": 25001}, True), ({"amount": 25000}, False),
    ({"customer_type": "vip", "customer_age_days": 900, "amount": 75001}, True), ({"customer_type": "vip", "customer_age_days": 900, "amount": 70000}, False),
    ({"amount": 100000, "currency": "ILS"}, True),                                                # 27.8k USD > 25k
])
def test_amount_limits_by_customer_type_are_in_usd(changes, violated):
    assert any(v.policy_id == "P2_AMOUNT_LIMIT_BY_CUSTOMER" for v in check_policies(tx(**changes))) is violated


@pytest.mark.parametrize("changes,violated", [({"payment_method": "wallet", "amount": 3001}, True), ({"payment_method": "wallet", "amount": 3000}, False),
                                              ({"payment_method": "card", "amount": 3001}, False)])
def test_wallet_limit_applies_to_wallets_only(changes, violated):
    assert any(v.policy_id == "P3_WALLET_LIMIT" for v in check_policies(tx(**changes))) is violated


@pytest.mark.parametrize("changes,violated", [({"payment_method": "bank_transfer", "merchant_category": "gaming"}, True),
                                              ({"payment_method": "bank_transfer", "merchant_category": "utilities"}, False),
                                              ({"payment_method": "card", "merchant_category": "gaming"}, False)])
def test_forbidden_combination_needs_all_fields_to_match(changes, violated):
    assert any(v.policy_id == "P4_NO_GAMING_BY_BANK_TRANSFER" for v in check_policies(tx(**changes))) is violated


def test_no_violation_for_an_ordinary_payment_and_strictest_picks_decline():
    assert check_policies(tx()) == [] and strictest([]) is None
    both = check_policies(tx(country="KP", payment_method="wallet", amount=4000))
    assert {v.policy_id for v in both} == {"P1_SANCTIONED_COUNTRY", "P3_WALLET_LIMIT"} and strictest(both) is Action.DECLINE


# --- the gate in the graph -------------------------------------------------------------------------------------------------------------------
def test_sanctioned_country_is_declined_before_any_tool_or_llm_work(llm):
    r = run_decision_graph(tx(country="KP"))
    assert r.decision.action is Action.DECLINE and r.decision.reason_codes == [ReasonCode.POLICY_BLOCK]
    assert r.graph_trace == ["input", "policy_gate", "policy_block", "finalize", "constraint_guard"]
    assert r.tool_trace == [] and llm == [] and r.llm_status == "skipped"
    assert r.blocked_by == [{"policy_id": "P1_SANCTIONED_COUNTRY", "action": "decline", "message": "Payments from sanctioned jurisdictions are prohibited"}]
    assert "P1_SANCTIONED_COUNTRY" in r.decision.explanation


def test_limit_violations_go_to_manual_review_with_the_policy_named(llm):
    r = run_decision_graph(tx(payment_method="wallet", amount=4000))
    assert r.decision.action is Action.MANUAL_REVIEW and r.decision.reason_codes == [ReasonCode.POLICY_BLOCK]
    assert [b["policy_id"] for b in r.blocked_by] == ["P3_WALLET_LIMIT"] and "Wallet payments above 3,000 USD" in r.decision.explanation


def test_policy_beats_the_unknown_country_fallback():
    r = run_decision_graph(tx(country="KP"))                                    # KP is not in the risk tables: policy still wins (decline, not review)
    assert r.decision.action is Action.DECLINE and r.graph_route == "normal"


def test_compliant_payments_are_unaffected(llm):
    r = run_decision_graph(tx())
    assert r.blocked_by == [] and r.decision.action is Action.ROUTE and "policy_block" not in r.graph_trace and llm == ["decision_review"]


def test_policy_decisions_are_audited(isolated_audit):
    r = run_decision_graph(tx(country="KP"))
    rec = isolated_audit.get(r.decision_id)
    assert rec.final_action == "decline" and rec.reason_codes == ["POLICY_BLOCK"] and any("policy block: P1_SANCTIONED_COUNTRY" in n for n in rec.technical_notes)


def test_policy_gate_logs_the_guardrail_decision(caplog):
    with caplog.at_level(logging.INFO):
        run_decision_graph(tx(country="KP"))
    line = next(r.getMessage() for r in caplog.records if "guardrail_decision" in r.getMessage())
    assert "stage=policy_gate" in line and "P1_SANCTIONED_COUNTRY" in line and "action=decline" in line


# --- the guard after the decision -----------------------------------------------------------------------------------------------------------
def test_guard_stays_silent_on_normal_decisions():
    assert run_decision_graph(tx()).guard_override is None


def test_guard_corrects_a_decision_that_violates_policy(monkeypatch, caplog):
    """Simulate an upstream bug: the gate misses a sanctioned payment (first check returns nothing) and the rules let it through.
    The guard - an independent second check - must catch it and make the outcome stricter."""
    real = policy.check_policies
    calls = {"n": 0}

    def flaky(t, policies=None):
        calls["n"] += 1
        return [] if calls["n"] == 1 else real(t, policies)                     # gate sees nothing, guard sees the truth

    monkeypatch.setattr(decision_graph, "check_policies", flaky)
    with caplog.at_level(logging.ERROR):
        r = run_decision_graph(tx(country="KP"))                                # unknown country -> fallback -> manual_review, but policy says decline
    assert r.decision.action is Action.DECLINE and r.decision.selected_provider is None and r.decision.reason_codes[0] is ReasonCode.POLICY_BLOCK
    assert r.guard_override and "P1_SANCTIONED_COUNTRY" in r.guard_override
    assert any("guardrail_override" in rec.getMessage() for rec in caplog.records)


def test_guard_catches_an_ineligible_provider(monkeypatch):
    """A routed decision naming a provider that cannot carry the payment is turned into a manual review."""
    from decision_engine import BaselineResult
    real_select = decision_graph.select_provider

    def bad_select(t, risk, candidates, rejected):
        result = real_select(t, risk, candidates, rejected)
        zeta = get_provider("zeta_budget")                                       # cards only, max 3,000 USD
        result.decision = result.decision.model_copy(update={"selected_provider": zeta.provider_id})
        return BaselineResult(result.decision, risk, result.candidates, rejected)

    monkeypatch.setattr(decision_graph, "select_provider", bad_select)
    r = run_decision_graph(tx(merchant_category="luxury", customer_type="vip", customer_age_days=900, amount=20000))   # far above zeta's 3,000 limit
    assert r.decision.action is Action.MANUAL_REVIEW and r.guard_override and "not eligible" in r.guard_override


# --- prompt, API, versioning ----------------------------------------------------------------------------------------------------------------
def test_llm_prompt_lists_the_policies_in_force():
    from decision_engine import decide_baseline
    t = tx()
    prompt = render_review_prompt(t, decide_baseline(t))
    assert "Business policies in force" in prompt and "P1_SANCTIONED_COUNTRY" in prompt and "never claim a policy was waived" in prompt
    assert len(policy_summary()) == 4


def test_api_returns_a_normal_200_with_the_blocked_format():
    r = client.post("/decision", json={**BASE, "country": "IR"})
    body = r.json()
    assert r.status_code == 200 and body["decision"]["action"] == "decline" and body["decision"]["reason_codes"] == ["POLICY_BLOCK"]
    assert body["blocked_by"][0]["policy_id"] == "P1_SANCTIONED_COUNTRY" and body["guard_override"] is None and body["llm_status"] == "skipped"


def test_violation_dataclass_is_hashable_and_immutable():
    v = Violation("P1", Action.DECLINE, "m")
    assert v in {v} and v.policy_id == "P1"
    with pytest.raises(AttributeError):
        v.policy_id = "P2"
