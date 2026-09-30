"""Decision pipeline whose data access goes through audited tool calls.

    Transaction -> risk_lookup -> [rules] -> provider_lookup -> cost_estimate (per eligible provider) -> [rules] -> Decision

The rules are exactly the baseline's (`decide_baseline`); only the way data is fetched changes. So the result must equal
the direct baseline - tested on hundreds of transactions - while every lookup is recorded in a trace.
"""
from dataclasses import dataclass

from decision_engine import BaselineResult, Candidate, DirectGatherer, decide_baseline, unassessed_result
from errors import AppError
from risk import RiskAssessment
from schemas import Action, Decision, ReasonCode, Transaction
from tools import ToolTrace, execute_tool


class ToolFailure(AppError):
    def __init__(self, tool: str, error: str):
        super().__init__(f"tool '{tool}' failed: {error}", status_code=502)
        self.tool = tool


class ToolGatherer(DirectGatherer):
    def __init__(self, trace: ToolTrace):
        self.trace = trace

    def _run(self, name: str, args: dict) -> dict:
        result = execute_tool(name, args, self.trace)
        if not result.ok:
            raise ToolFailure(name, result.error or "unknown error")
        return result.output

    def risk(self, tx: Transaction) -> RiskAssessment:
        out = self._run("risk_lookup", {"country": tx.country, "merchant_category": tx.merchant_category, "customer_type": tx.customer_type,
                                        "amount": tx.amount, "currency": tx.currency, "prior_chargebacks": tx.prior_chargebacks})
        return RiskAssessment(out["risk_score"], out["components"], [ReasonCode(r) for r in out["reason_codes"]])

    def eligible(self, tx: Transaction, risk: float) -> tuple[list[Candidate], dict[str, str]]:
        found = self._run("provider_lookup", {"country": tx.country, "currency": tx.currency, "payment_method": tx.payment_method,
                                              "amount": tx.amount, "risk": risk})
        candidates = []
        for provider_id in found["eligible"]:
            cost = self._run("cost_estimate", {"provider_id": provider_id, "amount": tx.amount, "risk": risk})
            candidates.append(Candidate(cost["provider_id"], cost["expected_cost"], cost["expected_approval_probability"],
                                        cost["latency_ms"], cost["score"]))
        return candidates, found["rejected"]


@dataclass
class ToolDecisionResult:
    baseline: BaselineResult
    trace: ToolTrace
    tool_failure: str | None = None

    @property
    def decision(self) -> Decision:
        return self.baseline.decision


def decide_with_tools(tx: Transaction) -> ToolDecisionResult:
    """Baseline rules over tool-fetched data. A failing tool never crashes the decision: it becomes a manual review."""
    trace = ToolTrace()
    try:
        return ToolDecisionResult(decide_baseline(tx, ToolGatherer(trace)), trace)
    except ToolFailure as failure:
        return ToolDecisionResult(unassessed_result(tx, Action.MANUAL_REVIEW, [ReasonCode.TOOL_ERROR]), trace, tool_failure=str(failure.message))
