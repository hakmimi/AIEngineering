"""Fast path: decisions where the LLM review adds cost and latency but no safety.

Evidence (Days 32-38): across 39 evaluation cases the LLM reviewer never escalated or changed a decision, and the rule
template scores at least as well on the explanation rubric as the LLM text. So the LLM is spent only where a second opinion
could plausibly matter (uncertain or unusual routed payments, and cases a human will read).

A transaction is on the fast path when the rules already make the outcome unambiguous:
  * DECLINE  - the LLM can never soften a decline, and the reason codes explain it fully;
  * ROUTE with low risk, an established customer, a clean chargeback history and an ordinary amount.
Everything else (manual review, borderline, new customers, unusual amounts) still gets the LLM review.
"""
from dataclasses import dataclass

from config import settings
from data_loader import load_risk_tables
from decision_engine import BaselineResult
from risk import amount_in_usd
from schemas import Action, CustomerType, Transaction


@dataclass(frozen=True)
class FastPathDecision:
    fast: bool
    reason: str


def evaluate_fast_path(tx: Transaction, baseline: BaselineResult) -> FastPathDecision:
    if not settings.fast_path_enabled:
        return FastPathDecision(False, "disabled")
    decision = baseline.decision
    if decision.action is Action.DECLINE:
        return FastPathDecision(True, "clear_decline")
    if decision.action is not Action.ROUTE:
        return FastPathDecision(False, "human_will_read_it")
    if baseline.risk.score >= settings.fast_path_max_risk:
        return FastPathDecision(False, "risk_above_fast_path_limit")
    if tx.customer_type is CustomerType.NEW:
        return FastPathDecision(False, "new_customer")
    if tx.prior_chargebacks > 0:
        return FastPathDecision(False, "chargeback_history")
    typical = load_risk_tables()["category_median_usd"][tx.merchant_category.value]
    if amount_in_usd(tx) > settings.fast_path_amount_multiple * typical:
        return FastPathDecision(False, "unusual_amount")
    return FastPathDecision(True, "routine_low_risk")
