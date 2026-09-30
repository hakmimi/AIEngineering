"""Evaluation of the decision agent: cases -> agent -> actual vs expected -> scores.

    Eval Dataset -> Decision Agent -> Actual Decision -> Expected Decision -> Score

Scoring is deterministic. Wrong decisions are split by the *direction* of the error, because they cost differently:
  unsafe_error     the agent was MORE permissive than any acceptable answer (routed what a human/decline should get)
  over_cautious    the agent was STRICTER than any acceptable answer (sent a routine payment to a human)
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from config import settings
from grounding import ungrounded_numbers
from schemas import Action, Decision, ReasonCode, Transaction

CASES_PATH = settings.data_dir / "eval" / "decision_cases.json"
RUBRIC_PATH = settings.data_dir / "eval" / "explanation_rubric.json"
PERMISSIVENESS = {Action.DECLINE: 0, Action.MANUAL_REVIEW: 1, Action.ROUTE: 2}      # higher = more permissive


@dataclass
class Expected:
    acceptable_actions: list[Action]
    acceptable_providers: list[str] | None
    route: str | None                   # None = the route is not part of the expectation (probe cases)
    must_include_reason_codes: list[str]


@dataclass
class EvalCase:
    id: str
    category: str
    description: str
    transaction: Transaction
    expected: Expected


@dataclass
class Actual:
    action: Action
    provider: str | None
    route: str
    reason_codes: list[str]
    explanation: str | None = None
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    llm_status: str | None = None


@dataclass
class CaseResult:
    case_id: str
    category: str
    actual: Actual
    action_ok: bool
    provider_ok: bool | None
    route_ok: bool
    reasons_ok: bool
    error_type: str | None                 # None | unsafe_error | over_cautious | wrong_action
    passed: bool
    explanation_score: dict | None = None
    details: list[str] = field(default_factory=list)


def load_cases(path: Path = CASES_PATH, limit: int | None = None) -> list[EvalCase]:
    """Load and validate cases: every transaction must parse, ids must be unique, expectations must be well-formed."""
    raw = json.loads(path.read_text(encoding="utf8"))
    seen, cases = set(), []
    for item in raw[:limit]:
        if item["id"] in seen:
            raise ValueError(f"duplicate case id {item['id']}")
        seen.add(item["id"])
        e = item["expected"]
        expected = Expected([Action(a) for a in e["acceptable_actions"]], e.get("acceptable_providers"), e.get("route", "normal"),
                            e.get("must_include_reason_codes", []))
        if not expected.acceptable_actions:
            raise ValueError(f"{item['id']}: no acceptable action")
        if Action.ROUTE not in expected.acceptable_actions and expected.acceptable_providers:
            raise ValueError(f"{item['id']}: providers expected but routing is not acceptable")
        cases.append(EvalCase(item["id"], item["category"], item["description"], Transaction(**item["transaction"]), expected))
    return cases


def score_case(case: EvalCase, actual: Actual) -> CaseResult:
    exp = case.expected
    action_ok = actual.action in exp.acceptable_actions
    details = []
    provider_ok = None
    if exp.acceptable_providers and actual.action is Action.ROUTE:
        provider_ok = actual.provider in exp.acceptable_providers
        if not provider_ok:
            details.append(f"provider {actual.provider} not in {exp.acceptable_providers}")
    route_ok = exp.route is None or actual.route == exp.route
    reasons_ok = all(code in actual.reason_codes for code in exp.must_include_reason_codes)
    if not reasons_ok:
        details.append(f"missing reason codes {[c for c in exp.must_include_reason_codes if c not in actual.reason_codes]}")
    if not route_ok:
        details.append(f"route {actual.route} != expected {exp.route}")

    error_type = None
    if not action_ok:
        most_permissive = max(PERMISSIVENESS[a] for a in exp.acceptable_actions)
        least_permissive = min(PERMISSIVENESS[a] for a in exp.acceptable_actions)
        if PERMISSIVENESS[actual.action] > most_permissive:
            error_type = "unsafe_error"
        elif PERMISSIVENESS[actual.action] < least_permissive:
            error_type = "over_cautious"
        else:
            error_type = "wrong_action"
        details.append(f"action {actual.action.value} not in {[a.value for a in exp.acceptable_actions]}")
    passed = action_ok and provider_ok is not False and reasons_ok and route_ok
    return CaseResult(case.id, case.category, actual, action_ok, provider_ok, route_ok, reasons_ok, error_type, passed, None, details)


def load_rubric() -> dict:
    return json.loads(RUBRIC_PATH.read_text(encoding="utf8"))


def actual_from_baseline(decision: Decision) -> Actual:
    """The rules-only agent has no notion of routes: everything it handles is the 'normal' route."""
    return Actual(decision.action, decision.selected_provider, "normal", [r.value for r in decision.reason_codes], decision.explanation)


def summarize(results: list[CaseResult]) -> dict:
    n = len(results)
    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r.category, []).append(r.passed)
    errors = {}
    for r in results:
        if r.error_type:
            errors[r.error_type] = errors.get(r.error_type, 0) + 1
    return {"cases": n, "pass_rate": round(sum(r.passed for r in results) / n, 3),
            "action_accuracy": round(sum(r.action_ok for r in results) / n, 3),
            "route_accuracy": round(sum(r.route_ok for r in results) / n, 3),
            "provider_accuracy": round(sum(1 for r in results if r.provider_ok) / max(sum(1 for r in results if r.provider_ok is not None), 1), 3),
            "errors": errors, "by_category": {c: round(sum(v) / len(v), 2) for c, v in by_cat.items()}}


# --- explanation scoring (deterministic implementation of data/eval/explanation_rubric.json) ---------------------------------------------------
ACTION_WORDS = {Action.ROUTE: ("routed", "route", "sent to"), Action.MANUAL_REVIEW: ("review", "human", "person"), Action.DECLINE: ("declin",)}
REASON_WORDS = {
    ReasonCode.LOW_RISK: ("low risk", "low-risk"), ReasonCode.MEDIUM_RISK: ("medium risk", "moderate risk", "medium-risk"),
    ReasonCode.HIGH_RISK: ("high risk", "high-risk", "risk score is above", "decline threshold"),
    ReasonCode.NEW_CUSTOMER_HIGH_AMOUNT: ("new customer", "large", "high amount", "high-value"),
    ReasonCode.PRIOR_CHARGEBACKS: ("chargeback",), ReasonCode.NO_ELIGIBLE_PROVIDER: ("no provider", "no eligible"),
    ReasonCode.CHEAPEST_ELIGIBLE: ("cheapest", "lowest fee", "lowest cost", "lowest-cost"),
    ReasonCode.HIGHEST_APPROVAL_RATE: ("approval",), ReasonCode.ONLY_ELIGIBLE_PROVIDER: ("only",),
    ReasonCode.BEST_OVERALL_SCORE: ("best", "balance"), ReasonCode.UNKNOWN_COUNTRY: ("country",),
    ReasonCode.EXTREME_AMOUNT: ("amount", "limit"),
    ReasonCode.CARD_TESTING_PATTERN: ("tiny", "small", "test"), ReasonCode.AMOUNT_ANOMALY: ("amount", "above", "unusual", "far"), ReasonCode.INCONSISTENT_PROFILE: ("inconsistent", "profile"),
    ReasonCode.LOW_CONFIDENCE: ("uncertain", "confiden", "borderline", "not sure"), ReasonCode.TOOL_ERROR: ("lookup", "failed"),
    ReasonCode.AI_ESCALATION: ("concern", "escalat", "review"), ReasonCode.POLICY_BLOCK: ("policy",), ReasonCode.INVALID_INPUT: ("invalid",),
}


def score_explanation(text: str | None, decision: Decision, tx: Transaction) -> dict:
    """Score 0-2 per rubric criterion. `facts` = everything the explanation may quote numbers from."""
    text = (text or "").strip()
    lowered = text.lower()
    if not text:
        return {"states_action": 0, "gives_correct_reason": 0, "grounded": 0, "business_language": 0, "concise": 0, "total": 0, "passed": False}
    states = 2 if any(w in lowered for w in ACTION_WORDS[decision.action]) and (decision.action is not Action.ROUTE or
                                                                              (decision.selected_provider or "") in text) else         1 if any(w in lowered for w in ACTION_WORDS[decision.action]) else 0
    primary = REASON_WORDS.get(decision.reason_codes[0], ())
    others = [w for code in decision.reason_codes[1:] for w in REASON_WORDS.get(code, ())]
    reason = 2 if any(w in lowered for w in primary) else 1 if any(w in lowered for w in others) else 0
    facts = json.dumps({**tx.model_dump(mode="json"), **decision.model_dump(mode="json")})
    grounded = 2 if not ungrounded_numbers(text, facts) else 0
    jargon = bool(re.search(r"\b[A-Z]{2,}(?:_[A-Z]+)+\b", text)) or "{" in text
    language = 0 if jargon else 2
    sentences = len([s for s in re.split(r"(?<=[.!?])\s+", text) if s])
    concise = 2 if sentences <= 3 and len(text) <= 450 else 1 if len(text) <= 700 else 0
    total = states + reason + grounded + language + concise
    return {"states_action": states, "gives_correct_reason": reason, "grounded": grounded, "business_language": language,
            "concise": concise, "total": total, "passed": total >= load_rubric()["pass_threshold"]}
