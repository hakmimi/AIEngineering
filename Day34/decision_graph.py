"""The decision agent as a LangGraph workflow.

    START -> input -> risk_tool -> rules --(risk rules decided)--------------------------------+
                                        \\--(need a provider)-> provider_tool -> cost_tool -> select   |
                                                                                          v          v
                                                                        llm_explain -> finalize -> END
    any tool failure  -> tool_error -> finalize -> END   (manual review, never a crash)

Nodes are plain functions `state -> partial update`; the business rules live in decision_engine (unchanged), data access
in tools, the LLM in ai_decision/prompts. The graph only decides *what runs next* and keeps the shared state
(which is why the same decision comes out of the graph as out of decide_ai - tested).
"""
import logging
import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from ai_decision import AIResult, LLMReview, apply_control_rules, validate_review
from decision_engine import BaselineResult, Candidate, log_baseline, risk_rule_decision, select_provider
from errors import ExternalServiceError
from llm import get_structured
from observability import log_event
from prompts import REVIEW_SCHEMA, render_review_prompt
from risk import RiskAssessment
from schemas import Action, Decision, ReasonCode, Transaction
from tools import ToolTrace, execute_tool
from usage import start_tracking, stop_tracking

logger = logging.getLogger("graph")
UNKNOWN_RISK_SCORE = 0.5


class DecisionState(TypedDict, total=False):
    transaction: Transaction
    risk: RiskAssessment
    candidates: list[Candidate]
    rejected: dict[str, str]
    baseline: BaselineResult
    review: LLMReview | None
    llm_status: str
    notes: Annotated[list[str], operator.add]
    decision: Decision
    error: dict                                        # {node, tool, message} when a tool failed
    tool_trace: ToolTrace
    trace: Annotated[list[str], operator.add]          # nodes visited, in order
    timings: Annotated[dict, lambda old, new: {**(old or {}), **new}]


def timed(name: str):
    def wrap(fn):
        def inner(state: DecisionState) -> dict:
            started = time.perf_counter()
            update = fn(state)
            ms = round((time.perf_counter() - started) * 1000, 2)
            log_event(logger, "graph_node", node=name, ms=ms, update_keys=sorted(update))
            return {**update, "timings": {name: ms}, "trace": [name]}
        inner.__name__ = fn.__name__
        return inner
    return wrap


def _tool(state: DecisionState, name: str, args: dict, node: str) -> tuple[dict | None, dict | None]:
    """Run a tool; returns (output, None) or (None, error-dict for the state)."""
    result = execute_tool(name, args, state["tool_trace"])
    if result.ok:
        return result.output, None
    return None, {"node": node, "tool": name, "message": result.error}


# --- nodes -------------------------------------------------------------------------------------------------------------
@timed("input")
def input_node(state: DecisionState) -> dict:
    """The transaction was validated by the API model; here we only initialise the run's shared objects."""
    return {"tool_trace": ToolTrace()}


@timed("risk_tool")
def risk_tool(state: DecisionState) -> dict:
    tx = state["transaction"]
    out, error = _tool(state, "risk_lookup", {"country": tx.country, "merchant_category": tx.merchant_category,
                                             "customer_type": tx.customer_type, "amount": tx.amount, "currency": tx.currency,
                                             "prior_chargebacks": tx.prior_chargebacks}, "risk_tool")
    if error:
        return {"error": error}
    return {"risk": RiskAssessment(out["risk_score"], out["components"], [ReasonCode(r) for r in out["reason_codes"]])}


@timed("rules")
def rules_node(state: DecisionState) -> dict:
    """Risk rules: decline / review decisions that need no provider data."""
    early = risk_rule_decision(state["transaction"], state["risk"])
    if early is None:
        return {}
    return {"baseline": BaselineResult(early, state["risk"], [], {})}


@timed("provider_tool")
def provider_tool(state: DecisionState) -> dict:
    tx, risk = state["transaction"], state["risk"]
    out, error = _tool(state, "provider_lookup", {"country": tx.country, "currency": tx.currency, "payment_method": tx.payment_method,
                                                 "amount": tx.amount, "risk": risk.score}, "provider_tool")
    return {"error": error} if error else {"rejected": out["rejected"], "candidates": [Candidate(p, 0, 0, 0, 0) for p in out["eligible"]]}


@timed("cost_tool")
def cost_tool(state: DecisionState) -> dict:
    tx, risk = state["transaction"], state["risk"]
    priced = []
    for candidate in state["candidates"]:
        out, error = _tool(state, "cost_estimate", {"provider_id": candidate.provider_id, "amount": tx.amount, "risk": risk.score}, "cost_tool")
        if error:
            return {"error": error}
        priced.append(Candidate(out["provider_id"], out["expected_cost"], out["expected_approval_probability"], out["latency_ms"], out["score"]))
    return {"candidates": priced}


@timed("select")
def select_node(state: DecisionState) -> dict:
    """Baseline decision node: rank the eligible candidates and choose (rules unchanged from Day 31)."""
    return {"baseline": select_provider(state["transaction"], state["risk"], state["candidates"], state["rejected"])}


@timed("llm_explain")
def llm_node(state: DecisionState) -> dict:
    tx, baseline, trace = state["transaction"], state["baseline"], state["tool_trace"]
    log_baseline(tx, baseline)
    try:
        raw = get_structured(render_review_prompt(tx, baseline, trace), REVIEW_SCHEMA, "decision_review")
        review, problems = validate_review(raw, tx, baseline, trace)
        return {"review": review, "llm_status": "ok" if review else "rejected_output", "notes": problems}
    except ExternalServiceError:
        return {"review": None, "llm_status": "unavailable", "notes": ["LLM unavailable - deterministic explanation used"]}


@timed("tool_error")
def tool_error_node(state: DecisionState) -> dict:
    """A data lookup failed: we do not know enough to decide, so a human does (Day 33 behaviour, now an explicit node)."""
    tx, error = state["transaction"], state["error"]
    risk = RiskAssessment(UNKNOWN_RISK_SCORE, {}, [])
    decision = Decision(transaction_id=tx.transaction_id, action=Action.MANUAL_REVIEW, reason_codes=[ReasonCode.TOOL_ERROR],
                        risk_score=UNKNOWN_RISK_SCORE)
    return {"baseline": BaselineResult(decision, risk, [], {}), "review": None, "llm_status": "skipped",
            "notes": [f"tool failure: tool '{error['tool']}' failed: {error['message']}"]}


@timed("finalize")
def finalize_node(state: DecisionState) -> dict:
    decision, control_notes = apply_control_rules(state["baseline"].decision, state.get("review"))
    return {"decision": decision, "notes": control_notes}


# --- edges (read state only) ---------------------------------------------------------------------------------------------------
def after_risk_tool(state: DecisionState) -> str:
    return "tool_error" if state.get("error") else "rules"


def after_rules(state: DecisionState) -> str:
    return "llm_explain" if state.get("baseline") else "provider_tool"     # risk rules decided -> skip provider tools


def after_provider_tool(state: DecisionState) -> str:
    return "tool_error" if state.get("error") else "cost_tool"


def after_cost_tool(state: DecisionState) -> str:
    return "tool_error" if state.get("error") else "select"


def build_graph():
    g = StateGraph(DecisionState)
    for name, fn in [("input", input_node), ("risk_tool", risk_tool), ("rules", rules_node), ("provider_tool", provider_tool),
                     ("cost_tool", cost_tool), ("select", select_node), ("llm_explain", llm_node),
                     ("tool_error", tool_error_node), ("finalize", finalize_node)]:
        g.add_node(name, fn)
    g.add_edge(START, "input")
    g.add_edge("input", "risk_tool")
    g.add_conditional_edges("risk_tool", after_risk_tool, {"rules": "rules", "tool_error": "tool_error"})
    g.add_conditional_edges("rules", after_rules, {"llm_explain": "llm_explain", "provider_tool": "provider_tool"})
    g.add_conditional_edges("provider_tool", after_provider_tool, {"cost_tool": "cost_tool", "tool_error": "tool_error"})
    g.add_conditional_edges("cost_tool", after_cost_tool, {"select": "select", "tool_error": "tool_error"})
    g.add_edge("select", "llm_explain")
    g.add_edge("llm_explain", "finalize")
    g.add_edge("tool_error", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


decision_graph = build_graph()


def run_decision_graph(tx: Transaction) -> AIResult:
    started = time.perf_counter()
    tracker, token = start_tracking()
    try:
        final = decision_graph.invoke({"transaction": tx, "notes": [], "trace": [], "timings": {}})
    finally:
        stop_tracking(token)
    review = final.get("review")
    result = AIResult(final["decision"], final["baseline"].decision, final.get("llm_status", "ok"), review, final.get("notes", []),
                      tracker.summary(), (time.perf_counter() - started) * 1000, final["tool_trace"].calls)
    log_event(logger, "graph_done", transaction_id=tx.transaction_id, trace=final["trace"], timings=final["timings"],
              final_action=result.decision.action.value, llm_status=result.llm_status, **result.usage)
    result.graph_trace, result.graph_timings = final["trace"], final["timings"]      # attached for the API response
    return result
