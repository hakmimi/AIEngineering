"""Deterministic explanation template.

Day 31 defines *what an explanation contains*; Day 32 asks the LLM to phrase it better. This template stays as the
fallback whenever the LLM is unavailable, so a decision never leaves the system without an explanation.
"""
from schemas import Action, Decision, ReasonCode

REASON_TEXT = {
    ReasonCode.LOW_RISK: "the transaction has a low risk score",
    ReasonCode.MEDIUM_RISK: "the transaction has a medium risk score",
    ReasonCode.HIGH_RISK: "the risk score is above the decline threshold",
    ReasonCode.NEW_CUSTOMER_HIGH_AMOUNT: "a new customer is making a large payment",
    ReasonCode.PRIOR_CHARGEBACKS: "the customer has prior chargebacks",
    ReasonCode.NO_ELIGIBLE_PROVIDER: "no provider can carry this payment (country, currency, method, amount or risk limits)",
    ReasonCode.CHEAPEST_ELIGIBLE: "it is the cheapest eligible provider",
    ReasonCode.HIGHEST_APPROVAL_RATE: "it has the highest expected approval probability",
    ReasonCode.ONLY_ELIGIBLE_PROVIDER: "it is the only provider that can carry this payment",
    ReasonCode.BEST_OVERALL_SCORE: "it offers the best balance of approval probability and cost",
    ReasonCode.AI_ESCALATION: "the AI reviewer raised a concern and recommended human review",
    ReasonCode.TOOL_ERROR: "a data lookup failed, so a person must decide",
    ReasonCode.POLICY_BLOCK: "a policy rule blocks this payment",
    ReasonCode.INVALID_INPUT: "the input was invalid",
}

ACTION_TEXT = {Action.ROUTE: "Routed to {provider}", Action.MANUAL_REVIEW: "Sent to manual review", Action.DECLINE: "Declined"}


def template_explanation(decision: Decision) -> str:
    head = ACTION_TEXT[decision.action].format(provider=decision.selected_provider)
    reasons = "; ".join(REASON_TEXT[r] for r in decision.reason_codes)
    tail = ""
    if decision.action is Action.ROUTE:
        tail = (f" Expected fee {decision.expected_cost:.2f}, expected approval probability "
                f"{decision.expected_approval_probability:.0%}.")
    return f"{head} because {reasons} (risk score {decision.risk_score:.2f}).{tail}"
