"""LLM prompts for the decision agent. The LLM explains and advises; it never decides."""
import json

from decision_engine import BaselineResult
from policy import policy_summary
from schemas import Transaction
from tools import ToolTrace

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "agrees_with_baseline": {"type": "boolean"},
        "concerns": {"type": "array", "items": {"type": "string"}},
        "escalate_to_review": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["explanation", "agrees_with_baseline", "concerns", "escalate_to_review", "confidence"],
    "additionalProperties": False,
}

REVIEW_PROMPT = """You are a payments risk analyst reviewing an automated routing decision. The decision was made by a
rules engine and is FINAL unless you recommend escalation. Your job:
1. explanation: 2-3 plain-English sentences for a business user saying what was decided and why. Use ONLY the facts in
   the data below (reason codes, risk components, providers). Do not invent numbers, providers or policies.
2. agrees_with_baseline: do the facts support the decision?
3. concerns: up to 3 short concerns worth a human's attention (empty list if none).
4. escalate_to_review: true ONLY if the baseline decision was "route" AND you see a concrete risk signal in the data that the
   rules under-weighted. Never escalate a decision that is already manual_review or decline. Do not escalate just because the
   amount or country is unfamiliar, and do not try to change the provider.
5. confidence: 0-1, how sure you are about your assessment.

Transaction:
{transaction}

Rules-engine decision:
{decision}

Risk breakdown (score 0-1; higher = riskier): {risk}
Eligible providers (best first): {candidates}
Rejected providers and why: {rejected}

Business policies in force (never suggest anything that conflicts with them, never claim a policy was waived):
{policies}

Tool results (the lookups the agent actually performed - base your explanation on these, not on general knowledge):
{tools}"""


def render_review_prompt(tx: Transaction, baseline: BaselineResult, trace: ToolTrace | None = None) -> str:
    d = baseline.decision
    decision = {"action": d.action.value, "selected_provider": d.selected_provider,
                "reason_codes": [r.value for r in d.reason_codes], "risk_score": d.risk_score,
                "expected_cost": d.expected_cost, "expected_approval_probability": d.expected_approval_probability}
    transaction = tx.model_dump(mode="json", exclude={"transaction_id"})
    return REVIEW_PROMPT.format(
        transaction=json.dumps(transaction), decision=json.dumps(decision), risk=json.dumps(baseline.risk.components),
        candidates=json.dumps([{"provider": c.provider_id, "fee": c.expected_cost, "approval": c.expected_approval_probability}
                               for c in baseline.candidates[:3]]),
        rejected=json.dumps(baseline.rejected), policies="\n".join(policy_summary()), tools=json.dumps(trace.for_prompt() if trace else []))


UNCERTAINTY_SCHEMA = {
    "type": "object",
    "properties": {"explanation": {"type": "string"}},
    "required": ["explanation"],
    "additionalProperties": False,
}

UNCERTAINTY_PROMPT = """An automated payment decision was routed to a human because it is uncertain. Write 2 plain-English
sentences for the human reviewer: what exactly is uncertain and what they should check. Use ONLY the facts below; do not
invent numbers, and do not say the payment is fraudulent or safe.

Uncertainty signals: {signals}
Automatic decision before escalation: {decision}
LLM reviewer's concerns: {concerns}
Risk breakdown: {risk}"""


def render_uncertainty_prompt(signals: list[str], baseline: BaselineResult, concerns: list[str]) -> str:
    d = baseline.decision
    decision = {"action": d.action.value, "provider": d.selected_provider, "risk_score": d.risk_score,
                "reason_codes": [r.value for r in d.reason_codes]}
    return UNCERTAINTY_PROMPT.format(signals=json.dumps(signals), decision=json.dumps(decision), concerns=json.dumps(concerns),
                                     risk=json.dumps(baseline.risk.components))


def source_text(tx: Transaction, baseline: BaselineResult, trace: ToolTrace | None = None) -> str:
    """Everything the model was allowed to quote numbers from (used by the grounding check)."""
    return render_review_prompt(tx, baseline, trace)
