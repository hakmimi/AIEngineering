"""Decision layer for tools: Query -> (rules | LLM) picks a tool -> execute -> answer.

Who decides? Cheap deterministic rules first (obvious arithmetic); the LLM decides everything else.
The tool never picks itself and the LLM never executes - see tools.py.
"""
import logging
import re
from dataclasses import dataclass

from errors import ExternalServiceError
from llm import get_answer, get_structured
from prompts import LLM_DOWN_ANSWER, render_tool_answer_prompt, render_tool_choice_prompt
from rag import build_response, get_rag_answer
from router import CLARIFY, SKIP, route_query
from timing import StepTimer
from tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)

TOOL_CHOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {"type": "string", "enum": [*TOOLS, "none"]},
        "query": {"type": "string"},
        "expression": {"type": "string"},
        "category": {"type": "string"},
        "numbers": {"type": "array", "items": {"type": "number"}},
        "weights": {"type": "array", "items": {"type": "number"}},
    },
    "required": ["tool", "query", "expression", "category", "numbers", "weights"],
    "additionalProperties": False,
}
_ARITHMETIC = re.compile(r"^\s*(?:what\s+is|what's|calculate|compute)?\s*([\d\s.,+\-*/()%^×÷]+?)\s*[=?]?\s*$", re.I)


@dataclass
class ToolDecision:
    tool: str
    arguments: dict
    decided_by: str  # "rule" | "llm" | "fallback"


_LIST_INTENT = re.compile(r"^\s*(list|show|which|what)\b.{0,40}\b(topics|places|categories|subjects)\b", re.I)
_CATEGORIES = ("city", "nature", "history", "culture", "technology", "society", "industry")


def rule_decision(question: str) -> ToolDecision | None:
    """Obvious cases need no LLM to pick the tool: pure arithmetic and "list the <category> topics"."""
    match = _ARITHMETIC.match(question)
    if match and re.search(r"\d\s*[+\-*/^×÷%]\s*[\d(]", match.group(1)):
        return ToolDecision("calculate", {"expression": match.group(1)}, "rule")
    if _LIST_INTENT.match(question):
        category = next((c for c in _CATEGORIES if re.search(rf"\b{c}\b", question, re.I)), None)
        return ToolDecision("list_topics", {"category": category}, "rule")
    return None


def llm_decision(question: str) -> ToolDecision:
    """LLM picks the tool and fills only that tool's arguments. On failure: safe default = search_docs."""
    try:
        choice = get_structured(render_tool_choice_prompt(question), TOOL_CHOICE_SCHEMA, "tool_choice")
    except ExternalServiceError:
        logger.warning("tool_choice_failed - defaulting to search_docs")
        return ToolDecision("search_docs", {"query": question}, "fallback")
    args = {"search_docs": {"query": choice["query"] or question},
            "calculate": {"expression": choice["expression"]},
            "calculate_score": {"values": choice["numbers"], "weights": choice["weights"] or None},
            "list_topics": {"category": choice["category"] or None}}.get(choice["tool"], {})
    return ToolDecision(choice["tool"], args, "llm")


def decide(question: str) -> ToolDecision:
    return rule_decision(question) or llm_decision(question)


def run_with_tools(question: str, top_k: int = 4) -> dict:
    timer = StepTimer()
    question = (question or "").strip()
    with timer.step("routing"):
        route = route_query(question, top_k)
    if route.name in (SKIP, CLARIFY):
        source = "smalltalk" if route.name == SKIP else "invalid_input"
        return build_response(question, route.direct_answer, source, route.name, timer)

    with timer.step("decide"):
        decision = decide(question)
    logger.info("tool_decision tool=%s by=%s args=%s", decision.tool, decision.decided_by, decision.arguments)
    extra = {"tool": {"name": decision.tool, "arguments": decision.arguments, "decided_by": decision.decided_by}}

    if decision.tool in ("search_docs", "none"):  # knowledge questions go through the normal RAG path
        result = get_rag_answer(question, top_k)
        return {**result, **extra, "source": result["source"]}

    with timer.step("tool"):
        outcome = execute_tool(decision.tool, decision.arguments)
    extra["tool"].update(ok=outcome.ok, output=outcome.output, error=outcome.error)

    try:
        with timer.step("answer"):
            text = get_answer(render_tool_answer_prompt(
                decision.tool, str(outcome.output if outcome.ok else f"ERROR: {outcome.error}"), question))
        answer, confidence = text["answer"], text.get("confidence") or 0.0
    except ExternalServiceError:
        answer, confidence = (str(outcome.output) if outcome.ok else LLM_DOWN_ANSWER), 0.0  # tool result still useful
    source = "tool" if outcome.ok else "tool_error"
    return build_response(question, answer, source, route.name, timer, confidence=confidence, extra=extra)
