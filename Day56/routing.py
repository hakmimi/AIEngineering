"""Routing decisions for the decision graph - pure functions, no I/O, easy to test.

Two places where the graph may leave the normal path:

1. classify_input(tx)  - BEFORE any work: inputs that are valid for the schema but that the agent should not decide
   on its own (unknown country, extreme amount, an inconsistent customer profile) go straight to a human.
2. uncertainty_signals(...) - AFTER the LLM review: a routed decision that the reviewer doubts (disagreement or low
   confidence) or that sits right below the review threshold for a new customer goes to a human as well.

Both only ever move a case toward MORE human oversight, never less.
"""
from dataclasses import dataclass

from config import settings
from data_loader import load_risk_tables
from risk import amount_in_usd
from schemas import Action, CustomerType, ReasonCode, Transaction

NORMAL, FALLBACK = "normal", "fallback"
EXTREME_AMOUNT_USD = 50_000
RETURNING_MIN_AGE_DAYS, VIP_MIN_AGE_DAYS = 7, 180
LOW_CONFIDENCE_BELOW = 0.5
BORDERLINE_MARGIN = 0.05


@dataclass(frozen=True)
class RouteChoice:
    route: str                          # normal | fallback
    reason_code: ReasonCode | None = None
    explanation: str | None = None


def classify_input(tx: Transaction) -> RouteChoice:
    if tx.country not in load_risk_tables()["country_risk"]:
        return RouteChoice(FALLBACK, ReasonCode.UNKNOWN_COUNTRY, f"country '{tx.country}' is not in the risk tables, so risk cannot be assessed")
    if amount_in_usd(tx) > EXTREME_AMOUNT_USD:
        return RouteChoice(FALLBACK, ReasonCode.EXTREME_AMOUNT, f"amount exceeds the automatic limit of {EXTREME_AMOUNT_USD:,} USD")
    if tx.customer_type is CustomerType.RETURNING and tx.customer_age_days < RETURNING_MIN_AGE_DAYS:
        return RouteChoice(FALLBACK, ReasonCode.INCONSISTENT_PROFILE, "a 'returning' customer with an account younger than 7 days is inconsistent")
    if tx.customer_type is CustomerType.VIP and tx.customer_age_days < VIP_MIN_AGE_DAYS:
        return RouteChoice(FALLBACK, ReasonCode.INCONSISTENT_PROFILE, "a 'vip' customer with an account younger than 180 days is inconsistent")
    return RouteChoice(NORMAL)


def uncertainty_signals(tx: Transaction, baseline_action: Action, risk_score: float, agrees: bool | None, confidence: float | None) -> list[str]:
    """Reasons to doubt a ROUTED decision. Empty list = not uncertain. Only routed decisions can be uncertain (others are already safe)."""
    if baseline_action is not Action.ROUTE:
        return []
    signals = []
    if agrees is False:
        signals.append("llm_disagrees")
    if confidence is not None and confidence < LOW_CONFIDENCE_BELOW:
        signals.append("llm_low_confidence")
    if tx.customer_type is CustomerType.NEW and settings.risk_review - BORDERLINE_MARGIN <= risk_score < settings.risk_review:
        signals.append("borderline_risk_new_customer")
    return signals
