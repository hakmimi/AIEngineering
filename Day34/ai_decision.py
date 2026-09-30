"""Hybrid decision: rules decide, the LLM explains and may only make the outcome SAFER.

    Transaction -> baseline (rules) -> LLM review (explanation, agreement, concerns, escalation flag) -> final decision

Control rules (each one is tested):
  * the baseline action stands, except  route -> manual_review  when the LLM escalates;
  * the LLM can never approve, change the provider, or soften manual_review / decline;
  * if the LLM is down or its output is unusable, the deterministic template explanation is used - the decision is unchanged.
"""
import logging
import time
from dataclasses import dataclass, field

from config import settings
from decision_engine import BaselineResult
from errors import ExternalServiceError
from explanations import template_explanation
from grounding import ungrounded_numbers
from llm import get_structured
from observability import log_event
from prompts import REVIEW_SCHEMA, render_review_prompt, source_text
from schemas import Action, Decision, ReasonCode, Transaction
from tool_pipeline import decide_with_tools
from tools import ToolTrace
from usage import start_tracking, stop_tracking

logger = logging.getLogger("decision")
MAX_CONCERNS, MAX_CONCERN_CHARS = 3, 200


@dataclass
class LLMReview:
    explanation: str
    agrees_with_baseline: bool
    concerns: list[str]
    escalate_to_review: bool
    confidence: float


@dataclass
class AIResult:
    decision: Decision                 # the final decision
    baseline: Decision                 # what the rules alone decided
    llm_status: str                    # ok | unavailable | rejected_output
    review: LLMReview | None = None
    notes: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    tool_trace: list[dict] = field(default_factory=list)
    graph_trace: list[str] = field(default_factory=list)
    graph_timings: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"decision": self.decision.model_dump(mode="json"), "baseline_decision": self.baseline.model_dump(mode="json"),
                "changed_by_ai": self.decision.action != self.baseline.action, "llm_status": self.llm_status,
                "llm": None if self.review is None else self.review.__dict__, "notes": self.notes,
                "usage": self.usage, "latency_ms": round(self.latency_ms, 1),
                "tool_trace": self.tool_trace,
                **({"graph": {"trace": self.graph_trace, "timings_ms": self.graph_timings}} if self.graph_trace else {})}


def validate_review(raw: dict, tx: Transaction, baseline: BaselineResult, trace: ToolTrace) -> tuple[LLMReview | None, list[str]]:
    """Accept the model's review only if it is usable and grounded; otherwise (None, why)."""
    explanation = (raw.get("explanation") or "").strip()
    if not explanation:
        return None, ["empty explanation"]
    if len(explanation) > settings.llm_max_explanation_chars:
        return None, [f"explanation longer than {settings.llm_max_explanation_chars} characters"]
    invented = ungrounded_numbers(explanation, source_text(tx, baseline, trace))
    if invented:
        return None, [f"explanation contains numbers not in the data: {invented}"]
    concerns = [c.strip()[:MAX_CONCERN_CHARS] for c in raw.get("concerns", []) if c.strip()][:MAX_CONCERNS]
    return LLMReview(explanation, bool(raw["agrees_with_baseline"]), concerns, bool(raw["escalate_to_review"]),
                     float(raw["confidence"])), []


def apply_control_rules(baseline: Decision, review: LLMReview | None) -> tuple[Decision, list[str]]:
    """The only ways the LLM can influence the outcome. Everything else is ignored by construction."""
    if review is None:
        return baseline.model_copy(update={"explanation": template_explanation(baseline)}), []
    final = baseline.model_copy(update={"explanation": review.explanation})
    notes: list[str] = []
    if review.escalate_to_review:
        if baseline.action is Action.ROUTE:
            final = final.model_copy(update={
                "action": Action.MANUAL_REVIEW, "selected_provider": None, "expected_cost": None,
                "expected_approval_probability": None, "reason_codes": [ReasonCode.AI_ESCALATION, *baseline.reason_codes]})
            notes.append("escalated from route to manual_review by the AI reviewer")
        else:
            notes.append(f"ignored escalation flag: baseline is already {baseline.action.value}")
    return final, notes


def decide_ai(tx: Transaction) -> AIResult:
    started = time.perf_counter()
    tooled = decide_with_tools(tx)                     # data comes from audited tool calls; rules are the baseline's
    baseline, trace = tooled.baseline, tooled.trace
    tracker, token = start_tracking()
    review, notes, status = None, [], "ok"
    try:
        raw = get_structured(render_review_prompt(tx, baseline, trace), REVIEW_SCHEMA, "decision_review")
        review, problems = validate_review(raw, tx, baseline, trace)
        if review is None:
            status, notes = "rejected_output", problems
    except ExternalServiceError:
        status, notes = "unavailable", ["LLM unavailable - deterministic explanation used"]
    finally:
        stop_tracking(token)

    final, control_notes = apply_control_rules(baseline.decision, review)
    if tooled.tool_failure:
        notes = [f"tool failure: {tooled.tool_failure}", *notes]
    result = AIResult(final, baseline.decision, status, review, notes + control_notes, tracker.summary(),
                      (time.perf_counter() - started) * 1000, trace.calls)
    log_event(logger, "decision_made", mode="ai", transaction_id=tx.transaction_id, baseline_action=baseline.decision.action.value,
              final_action=final.action.value, llm_status=status, agrees=review.agrees_with_baseline if review else None,
              escalate=review.escalate_to_review if review else None, concerns=len(review.concerns) if review else 0,
              changed=final.action != baseline.decision.action, notes=result.notes, tool_calls=len(trace.calls), **result.usage)
    return result
