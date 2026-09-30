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
from audit import audit_store, new_decision_id, record_decision
from data_loader import load_providers
from decision_engine import BaselineResult, Candidate, ineligible_reason, log_baseline, risk_rule_decision, select_provider
from errors import ExternalServiceError
from fast_path import evaluate_fast_path
from grounding import ungrounded_numbers
from llm import get_structured
from observability import decision_id_var, log_event
from policy import STRICTNESS, check_policies, strictest
from prompts import REVIEW_SCHEMA, UNCERTAINTY_SCHEMA, render_review_prompt, render_uncertainty_prompt
from risk import RiskAssessment
from routing import FALLBACK, classify_input, uncertainty_signals
from schemas import Action, Decision, ReasonCode, Transaction
from tools import ToolTrace, execute_tool
from usage import start_tracking, stop_tracking
from version import AGENT_VERSION

logger = logging.getLogger("graph")
UNKNOWN_RISK_SCORE = 0.5


class DecisionState(TypedDict, total=False):
    transaction: Transaction
    route: str                                         # normal | fallback   (set by route_input)
    route_reason: str | None
    fallback_code: ReasonCode | None
    uncertainty: list[str]                             # signals that made the decision uncertain
    fast_path: str | None                              # why the LLM review was skipped (None = LLM was used)
    violations: list                                   # policy violations found by policy_gate
    guard_override: str | None                         # set by constraint_guard if it had to correct the final decision
    uncertainty_text: str | None
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


@timed("policy_gate")
def policy_gate_node(state: DecisionState) -> dict:
    """Non-negotiable business policies are checked first: a violation needs no tools and no LLM, only a safe explained decision."""
    violations = check_policies(state["transaction"])
    if violations:
        log_event(logger, "guardrail_decision", stage="policy_gate", transaction_id=state["transaction"].transaction_id,
                  policy_ids=[v.policy_id for v in violations], action=strictest(violations).value)
    return {"violations": violations}


@timed("policy_block")
def policy_block_node(state: DecisionState) -> dict:
    tx, violations = state["transaction"], state["violations"]
    action = strictest(violations)
    decision = Decision(transaction_id=tx.transaction_id, action=action, reason_codes=[ReasonCode.POLICY_BLOCK], risk_score=UNKNOWN_RISK_SCORE)
    decision.explanation = "; ".join(v.message for v in violations) + f". Policy: {', '.join(v.policy_id for v in violations)}."
    return {"baseline": BaselineResult(decision, RiskAssessment(UNKNOWN_RISK_SCORE, {}, []), [], {}), "review": None, "llm_status": "skipped",
            "notes": [f"policy block: {', '.join(v.policy_id for v in violations)}"]}


@timed("route_input")
def route_input_node(state: DecisionState) -> dict:
    """Edge cases the agent must not decide alone (unknown country, extreme amount, inconsistent profile) -> fallback path."""
    choice = classify_input(state["transaction"])
    log_event(logger, "graph_route", route=choice.route, reason=choice.reason_code.value if choice.reason_code else None,
              transaction_id=state["transaction"].transaction_id)
    return {"route": choice.route, "route_reason": choice.explanation, "fallback_code": choice.reason_code}


@timed("fallback")
def fallback_node(state: DecisionState) -> dict:
    """No tools, no LLM: a human decides, with a precise reason code and a template explanation."""
    tx = state["transaction"]
    risk = RiskAssessment(UNKNOWN_RISK_SCORE, {}, [])
    decision = Decision(transaction_id=tx.transaction_id, action=Action.MANUAL_REVIEW, reason_codes=[state["fallback_code"]],
                        risk_score=UNKNOWN_RISK_SCORE)
    return {"baseline": BaselineResult(decision, risk, [], {}), "review": None, "llm_status": "skipped",
            "notes": [f"fallback route: {state['route_reason']}"]}


@timed("uncertainty_review")
def uncertainty_node(state: DecisionState) -> dict:
    """Explain WHY a routed decision is being sent to a human (LLM, validated; template if the LLM is unavailable)."""
    baseline, review = state["baseline"], state.get("review")
    signals = state["uncertainty"]
    log_event(logger, "graph_uncertain", transaction_id=state["transaction"].transaction_id, signals=signals)
    text = None
    try:
        prompt = render_uncertainty_prompt(signals, baseline, review.concerns if review else [])
        candidate = (get_structured(prompt, UNCERTAINTY_SCHEMA, "uncertainty_explanation").get("explanation") or "").strip()
        if candidate and len(candidate) <= 600 and not ungrounded_numbers(candidate, prompt):
            text = candidate
    except ExternalServiceError:
        pass
    if text is None:
        text = "Sent to manual review because the automatic decision is uncertain: " + ", ".join(s.replace("_", " ") for s in signals) + "."
    return {"uncertainty_text": text}


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


@timed("fast_explain")
def fast_explain_node(state: DecisionState) -> dict:
    """Fast path: the rules' outcome is unambiguous, so skip the LLM (no call, no cost, ~2 s saved). Template explanation is used."""
    verdict = evaluate_fast_path(state["transaction"], state["baseline"])
    log_baseline(state["transaction"], state["baseline"])
    log_event(logger, "graph_fast_path", transaction_id=state["transaction"].transaction_id, reason=verdict.reason)
    return {"review": None, "llm_status": "skipped_fast_path", "fast_path": verdict.reason, "uncertainty": [],
            "notes": [f"fast path: {verdict.reason} - LLM review skipped"]}


@timed("llm_explain")
def llm_node(state: DecisionState) -> dict:
    tx, baseline, trace = state["transaction"], state["baseline"], state["tool_trace"]
    log_baseline(tx, baseline)
    review, status, notes = None, "unavailable", ["LLM unavailable - deterministic explanation used"]
    try:
        raw = get_structured(render_review_prompt(tx, baseline, trace), REVIEW_SCHEMA, "decision_review")
        review, problems = validate_review(raw, tx, baseline, trace)
        status, notes = ("ok" if review else "rejected_output"), problems
    except ExternalServiceError:
        pass
    # Uncertainty is decided here, where the review is at hand, and stored in state for the conditional edge to read.
    signals = uncertainty_signals(tx, baseline.decision.action, baseline.risk.score,
                                  review.agrees_with_baseline if review else None, review.confidence if review else None)
    return {"review": review, "llm_status": status, "notes": notes, "uncertainty": signals}


@timed("tool_error")
def tool_error_node(state: DecisionState) -> dict:
    """A data lookup failed: we do not know enough to decide, so a human does (Day 33 behaviour, now an explicit node)."""
    tx, error = state["transaction"], state["error"]
    risk = RiskAssessment(UNKNOWN_RISK_SCORE, {}, [])
    decision = Decision(transaction_id=tx.transaction_id, action=Action.MANUAL_REVIEW, reason_codes=[ReasonCode.TOOL_ERROR],
                        risk_score=UNKNOWN_RISK_SCORE)
    return {"baseline": BaselineResult(decision, risk, [], {}), "review": None, "llm_status": "skipped",
            "notes": [f"tool failure: tool '{error['tool']}' failed: {error['message']}"]}


@timed("constraint_guard")
def constraint_guard_node(state: DecisionState) -> dict:
    """Independent last check of invariants that must hold on EVERY output. It should never fire; if it does it fails safe and shouts."""
    tx, decision = state["transaction"], state["decision"]
    problems = []
    violations = check_policies(tx)
    stricter = strictest(violations)
    if stricter is not None and STRICTNESS.get(decision.action, 0) < STRICTNESS[stricter]:
        problems.append("policy: " + ", ".join(v.policy_id for v in violations))
    if decision.action is Action.ROUTE:
        provider = next((p for p in load_providers() if p.provider_id == decision.selected_provider), None)
        if provider is None or ineligible_reason(provider, tx, decision.risk_score) is not None:
            problems.append(f"provider {decision.selected_provider} is not eligible")
    if not problems:
        return {}
    log_event(logger, "guardrail_override", level=logging.ERROR, transaction_id=tx.transaction_id, problems=problems,
              original_action=decision.action.value)
    fixed = decision.model_copy(update={"action": stricter or Action.MANUAL_REVIEW, "selected_provider": None, "expected_cost": None,
                                        "expected_approval_probability": None, "reason_codes": [ReasonCode.POLICY_BLOCK, *decision.reason_codes]})
    return {"decision": fixed, "guard_override": "; ".join(problems), "notes": [f"constraint guard override: {'; '.join(problems)}"]}


@timed("finalize")
def finalize_node(state: DecisionState) -> dict:
    review = state.get("review")
    code = ReasonCode.AI_ESCALATION
    if state.get("uncertainty"):                       # uncertainty always escalates a routed decision (toward a human)
        code = ReasonCode.LOW_CONFIDENCE
        review = LLMReview(state["uncertainty_text"], review.agrees_with_baseline if review else True,
                           review.concerns if review else [], True, review.confidence if review else 0.0)
    decision, control_notes = apply_control_rules(state["baseline"].decision, review, code)
    return {"decision": decision, "notes": control_notes}


# --- edges (read state only) ---------------------------------------------------------------------------------------------------
def after_policy_gate(state: DecisionState) -> str:
    return "policy_block" if state.get("violations") else "route_input"


def after_route_input(state: DecisionState) -> str:
    return "fallback" if state["route"] == FALLBACK else "risk_tool"


def after_llm(state: DecisionState) -> str:
    """Uncertain routed decisions go to the uncertainty node; everything else straight to finalize."""
    return "uncertainty_review" if state.get("uncertainty") else "finalize"


def after_risk_tool(state: DecisionState) -> str:
    return "tool_error" if state.get("error") else "rules"


def after_baseline(state: DecisionState) -> str:
    """Once the rules have decided: unambiguous outcomes take the fast path, the rest get the LLM review."""
    return "fast_explain" if evaluate_fast_path(state["transaction"], state["baseline"]).fast else "llm_explain"


def after_rules(state: DecisionState) -> str:
    if state.get("baseline"):                      # risk rules decided -> skip provider tools
        return after_baseline(state)
    return "provider_tool"


def after_provider_tool(state: DecisionState) -> str:
    return "tool_error" if state.get("error") else "cost_tool"


def after_cost_tool(state: DecisionState) -> str:
    return "tool_error" if state.get("error") else "select"


def build_graph():
    g = StateGraph(DecisionState)
    for name, fn in [("input", input_node), ("policy_gate", policy_gate_node), ("policy_block", policy_block_node), ("constraint_guard", constraint_guard_node),
                     ("route_input", route_input_node), ("fallback", fallback_node),
                     ("uncertainty_review", uncertainty_node), ("risk_tool", risk_tool), ("rules", rules_node), ("provider_tool", provider_tool),
                     ("cost_tool", cost_tool), ("select", select_node), ("llm_explain", llm_node), ("fast_explain", fast_explain_node),
                     ("tool_error", tool_error_node), ("finalize", finalize_node)]:
        g.add_node(name, fn)
    g.add_edge(START, "input")
    g.add_edge("input", "policy_gate")
    g.add_conditional_edges("policy_gate", after_policy_gate, {"policy_block": "policy_block", "route_input": "route_input"})
    g.add_edge("policy_block", "finalize")
    g.add_conditional_edges("route_input", after_route_input, {"fallback": "fallback", "risk_tool": "risk_tool"})
    g.add_edge("fallback", "finalize")
    g.add_edge("uncertainty_review", "finalize")
    g.add_conditional_edges("risk_tool", after_risk_tool, {"rules": "rules", "tool_error": "tool_error"})
    g.add_conditional_edges("rules", after_rules, {"llm_explain": "llm_explain", "fast_explain": "fast_explain", "provider_tool": "provider_tool"})
    g.add_conditional_edges("provider_tool", after_provider_tool, {"cost_tool": "cost_tool", "tool_error": "tool_error"})
    g.add_conditional_edges("cost_tool", after_cost_tool, {"select": "select", "tool_error": "tool_error"})
    g.add_conditional_edges("select", after_baseline, {"llm_explain": "llm_explain", "fast_explain": "fast_explain"})
    g.add_edge("fast_explain", "finalize")
    g.add_conditional_edges("llm_explain", after_llm, {"uncertainty_review": "uncertainty_review", "finalize": "finalize"})
    g.add_edge("tool_error", "finalize")
    g.add_edge("finalize", "constraint_guard")
    g.add_edge("constraint_guard", END)
    return g.compile()


decision_graph = build_graph()


def run_decision_graph(tx: Transaction, store=None) -> AIResult:
    started = time.perf_counter()
    decision_id = new_decision_id()
    id_token = decision_id_var.set(decision_id)          # every log line of this decision carries the id
    tracker, token = start_tracking()
    try:
        final = decision_graph.invoke({"transaction": tx, "notes": [], "trace": [], "timings": {}})
    finally:
        stop_tracking(token)
    review = final.get("review")
    result = AIResult(final["decision"], final["baseline"].decision, final.get("llm_status", "ok"), review, final.get("notes", []),
                      tracker.summary(), (time.perf_counter() - started) * 1000, final["tool_trace"].calls)
    result.graph_trace, result.graph_timings = final["trace"], final["timings"]      # attached for the API response
    result.graph_route, result.graph_route_reason = final.get("route", "normal"), final.get("route_reason")
    result.fast_path = final.get("fast_path")
    result.blocked_by = [{"policy_id": v.policy_id, "action": v.action.value, "message": v.message} for v in final.get("violations", [])]
    result.guard_override = final.get("guard_override")
    if final.get("uncertainty"):
        result.graph_route = "uncertain"
        result.graph_route_reason = ", ".join(final["uncertainty"])
    result.decision_id, result.risk_components = decision_id, final["baseline"].risk.components
    result.audit_recorded = record_decision(decision_id, result, tx, AGENT_VERSION, store or audit_store)
    log_event(logger, "graph_done", transaction_id=tx.transaction_id, trace=final["trace"], timings=final["timings"],
              final_action=result.decision.action.value, llm_status=result.llm_status, audit_recorded=result.audit_recorded,
              fast_path=result.fast_path, latency_ms=round(result.latency_ms, 1), **result.usage)
    decision_id_var.reset(id_token)
    return result
