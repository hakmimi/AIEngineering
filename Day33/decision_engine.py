"""Baseline decision engine: eligibility rules -> scoring -> selection -> action + reason codes. No LLM.

    Transaction -> risk -> hard rules (decline / review) -> eligible providers -> score -> best provider -> Decision

Design notes
* The order matters and is fixed: risk rules first (a risky transaction is never "routed cheaply"), then hard
  capability constraints, then ranking. Every branch adds a reason code, so every decision is explainable.
* Ranking = expected merchant value per attempt: approval_probability * (1 - fee/amount), with a tiny latency tie-break.
  Approval probability is the agent's *estimate* (provider base rate x uptime x risk penalty), not the hidden truth.
"""
import logging
from dataclasses import asdict, dataclass

from config import settings
from data_loader import load_providers
from observability import log_event
from risk import RiskAssessment, amount_in_usd, compute_risk
from schemas import Action, CustomerType, Decision, ReasonCode, Transaction
from simulation import Provider, can_carry

logger = logging.getLogger("decision")

RISK_PENALTY = 0.40           # approval falls by 40% at risk 1.0 (same shape the simulation uses, learned "by experience")
LATENCY_WEIGHT = 0.00002      # per ms - only breaks ties between similar providers
LOW_RISK_BELOW = 0.25


@dataclass
class Candidate:
    provider_id: str
    expected_cost: float
    expected_approval_probability: float
    latency_ms: int
    score: float


@dataclass
class BaselineResult:
    decision: Decision
    risk: RiskAssessment
    candidates: list[Candidate]          # eligible providers, best first (empty when none / not evaluated)
    rejected: dict[str, str]             # provider_id -> why it was not eligible

    def to_dict(self) -> dict:
        return {"decision": self.decision.model_dump(mode="json"),
                "risk": {"score": self.risk.score, "components": self.risk.components},
                "candidates": [asdict(c) for c in self.candidates], "rejected_providers": self.rejected}


def ineligible_reason(provider: Provider, tx: Transaction, risk: float) -> str | None:
    """None = eligible. Otherwise a short machine-readable cause."""
    if provider.supported_countries is not None and tx.country not in provider.supported_countries:
        return "country_not_supported"
    if tx.currency not in provider.supported_currencies:
        return "currency_not_supported"
    if tx.payment_method not in provider.supported_methods:
        return "method_not_supported"
    if tx.amount > provider.max_amount:
        return "amount_above_limit"
    if risk > provider.max_risk:
        return "risk_above_tolerance"
    assert can_carry(provider, tx.country, tx.currency.value, tx.payment_method.value, tx.amount)   # both views agree
    return None


def score_provider(provider: Provider, tx: Transaction, risk: float) -> Candidate:
    cost = round(tx.amount * provider.fee_percent / 100 + provider.fee_fixed, 2)
    approval = round(provider.base_approval_rate * provider.uptime * (1 - RISK_PENALTY * risk), 4)
    score = approval * (1 - cost / tx.amount) - LATENCY_WEIGHT * provider.avg_latency_ms
    return Candidate(provider.provider_id, cost, approval, provider.avg_latency_ms, round(score, 5))


def _selection_reasons(best: Candidate, candidates: list[Candidate]) -> list[ReasonCode]:
    if len(candidates) == 1:                     # "cheapest of one" would be a misleading explanation
        return [ReasonCode.ONLY_ELIGIBLE_PROVIDER]
    reasons = []
    if best.expected_cost == min(c.expected_cost for c in candidates):
        reasons.append(ReasonCode.CHEAPEST_ELIGIBLE)
    if best.expected_approval_probability == max(c.expected_approval_probability for c in candidates):
        reasons.append(ReasonCode.HIGHEST_APPROVAL_RATE)
    return reasons or [ReasonCode.BEST_OVERALL_SCORE]


def _decision(tx: Transaction, action: Action, reasons: list[ReasonCode], risk: RiskAssessment,
              best: Candidate | None = None) -> Decision:
    return Decision(transaction_id=tx.transaction_id, action=action, reason_codes=reasons, risk_score=risk.score,
                    selected_provider=best.provider_id if best and action is Action.ROUTE else None,
                    expected_cost=best.expected_cost if best and action is Action.ROUTE else None,
                    expected_approval_probability=best.expected_approval_probability if best and action is Action.ROUTE else None)


class DirectGatherer:
    """Reads reference data with plain function calls (Day 31 behaviour)."""

    def risk(self, tx: Transaction) -> RiskAssessment:
        return compute_risk(tx)

    def eligible(self, tx: Transaction, risk: float) -> tuple[list[Candidate], dict[str, str]]:
        rejected: dict[str, str] = {}
        candidates: list[Candidate] = []
        for provider in load_providers():
            cause = ineligible_reason(provider, tx, risk)
            if cause:
                rejected[provider.provider_id] = cause
            else:
                candidates.append(score_provider(provider, tx, risk))
        return candidates, rejected


def decide_baseline(tx: Transaction, gatherer: DirectGatherer | None = None) -> BaselineResult:
    """Rules only. `gatherer` decides HOW data is fetched (direct calls or audited tool calls); the rules are the same."""
    gatherer = gatherer or DirectGatherer()
    risk = gatherer.risk(tx)

    # 1. risk rules ------------------------------------------------------------------------------------------------
    if risk.score >= settings.risk_decline:
        result = BaselineResult(_decision(tx, Action.DECLINE, [ReasonCode.HIGH_RISK, *risk.reason_codes], risk), risk, [], {})
    elif risk.score >= settings.risk_review:
        result = BaselineResult(_decision(tx, Action.MANUAL_REVIEW, [ReasonCode.MEDIUM_RISK, *risk.reason_codes], risk), risk, [], {})
    elif tx.customer_type is CustomerType.NEW and amount_in_usd(tx) > settings.new_customer_review_usd:
        result = BaselineResult(_decision(tx, Action.MANUAL_REVIEW, [ReasonCode.NEW_CUSTOMER_HIGH_AMOUNT, *risk.reason_codes], risk), risk, [], {})
    else:
        # 2. eligibility (hard constraints) ---------------------------------------------------------------------------
        candidates, rejected = gatherer.eligible(tx, risk.score)
        candidates.sort(key=lambda c: c.score, reverse=True)
        if not candidates:
            result = BaselineResult(_decision(tx, Action.MANUAL_REVIEW, [ReasonCode.NO_ELIGIBLE_PROVIDER, *risk.reason_codes], risk), risk, [], rejected)
        else:
            # 3. selection ------------------------------------------------------------------------------------------------
            best = candidates[0]
            level = ReasonCode.LOW_RISK if risk.score < LOW_RISK_BELOW else ReasonCode.MEDIUM_RISK
            reasons = [level, *_selection_reasons(best, candidates), *risk.reason_codes]
            result = BaselineResult(_decision(tx, Action.ROUTE, reasons, risk, best), risk, candidates, rejected)

    d = result.decision
    log_event(logger, "decision_made", mode="baseline", transaction_id=tx.transaction_id, amount=tx.amount, currency=tx.currency.value,
              country=tx.country, customer_type=tx.customer_type.value, risk_score=risk.score, action=d.action.value,
              provider=d.selected_provider, reasons=[r.value for r in d.reason_codes],
              eligible=[c.provider_id for c in result.candidates], rejected=result.rejected)
    return result
