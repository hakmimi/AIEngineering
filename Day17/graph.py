"""Day 16: conditional routing inside the graph.

    START -> receive_query -> route_query --+--> direct_answer -----------------------> END
                                            +--> select_tool -+-> run_tool -> tool_answer -> END   (tool)
                                            |                 +-> retrieve_context (search_docs / none)
                    |                       +--> fallback_response --------------------> END
                    +-- blank -> END        +--> retrieve_context -> call_llm ---------> END   (rag)

The router node writes its decision into state (route, query_type, route_reason, routed_by); the
conditional edge only *reads* that state to choose the next node - decision and branching are separate.
"""
import logging
import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from errors import ExternalServiceError
from intent import DIRECT, DIRECT_DEFAULT, FALLBACK, FALLBACK_ANSWER, RAG, TOOL, classify
from llm import get_answer
from prompts import LLM_DOWN_ANSWER, NO_CONTEXT_ANSWER, render_rag_prompt, render_tool_answer_prompt
from rag import build_context, validate_context
from retrieval import get_relevant_chunks
from tool_agent import llm_decision, rule_decision
from tools import execute_tool

logger = logging.getLogger(__name__)


class RagState(TypedDict, total=False):
    question: str
    top_k: int
    route: str                       # direct | rag | fallback         (set by route_query)
    query_type: str                  # simple | complex                (set by route_query)
    route_reason: str
    routed_by: str                   # rule | llm
    tool_name: str                   # set by select_tool
    tool_args: dict
    tool_decided_by: str             # rule | llm | fallback
    tool_result: dict                # {ok, output, error} set by run_tool
    chunks: list[dict]
    answer: str
    confidence: float
    source: str                      # rag | no_context | fallback_error | invalid_input | direct | fallback | tool | tool_error
    trace: Annotated[list[str], operator.add]
    timings: Annotated[dict, lambda old, new: {**(old or {}), **new}]


def timed(name: str):
    def wrap(fn):
        def inner(state: RagState) -> dict:
            started = time.perf_counter()
            update = fn(state)
            ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info("graph_node node=%s ms=%s update_keys=%s", name, ms, sorted(update))
            return {**update, "timings": {name: ms}, "trace": [name]}
        inner.__name__ = fn.__name__
        return inner
    return wrap


# --- nodes ---------------------------------------------------------------------------
@timed("receive_query")
def receive_query(state: RagState) -> dict:
    question = " ".join((state.get("question") or "").split())
    if not question:
        return {"question": "", "answer": "Please provide a question.", "source": "invalid_input", "chunks": []}
    return {"question": question, "top_k": state.get("top_k") or 4}


@timed("route_query")
def route_query_node(state: RagState) -> dict:
    """Decide the path and remember why (state enrichment). Never raises: the LLM classifier fails safe."""
    d = classify(state["question"])
    logger.info("graph_route route=%s type=%s reason=%s by=%s", d.route, d.query_type, d.reason, d.by)
    update = {"route": d.route, "query_type": d.query_type, "route_reason": d.reason, "routed_by": d.by}
    if d.answer:
        update["answer"] = d.answer          # canned reply for direct/fallback, used by those nodes
    return update


@timed("direct_answer")
def direct_answer(state: RagState) -> dict:
    return {"answer": state.get("answer") or DIRECT_DEFAULT, "source": "direct", "confidence": 1.0, "chunks": []}


@timed("fallback_response")
def fallback_response(state: RagState) -> dict:
    return {"answer": state.get("answer") or FALLBACK_ANSWER, "source": "fallback", "confidence": 0.0, "chunks": []}


@timed("select_tool")
def select_tool(state: RagState) -> dict:
    """Who picks the tool? Rules first (free, exact); the LLM only for what the rules can't recognise."""
    decision = rule_decision(state["question"]) or llm_decision(state["question"])
    logger.info("graph_tool_selected tool=%s by=%s args=%s", decision.tool, decision.decided_by, decision.arguments)
    return {"tool_name": decision.tool, "tool_args": decision.arguments, "tool_decided_by": decision.decided_by}


@timed("run_tool")
def run_tool(state: RagState) -> dict:
    """Execute the selected tool. Inputs and outputs are validated inside execute_tool; it never raises."""
    outcome = execute_tool(state["tool_name"], state["tool_args"])
    return {"tool_result": {"ok": outcome.ok, "output": outcome.output, "error": outcome.error}}


@timed("tool_answer")
def tool_answer(state: RagState) -> dict:
    """Turn the validated tool result into a sentence. If the LLM is down the raw result is still returned."""
    result = state["tool_result"]
    shown = str(result["output"]) if result["ok"] else f"ERROR: {result['error']}"
    try:
        text = get_answer(render_tool_answer_prompt(state["tool_name"], shown, state["question"]))
        answer, confidence = text["answer"], text.get("confidence") or 0.0
    except ExternalServiceError:
        answer, confidence = (shown if result["ok"] else LLM_DOWN_ANSWER), 0.0
    return {"answer": answer, "confidence": confidence, "source": "tool" if result["ok"] else "tool_error"}


@timed("retrieve_context")
def retrieve_context(state: RagState) -> dict:
    complex_query = state.get("query_type") == "complex"
    top_k = max(state["top_k"], 6) if complex_query else min(state["top_k"], 3)
    return {"chunks": get_relevant_chunks(state["question"], top_k, None, wide=complex_query)}


@timed("call_llm")
def call_llm(state: RagState) -> dict:
    chunks = state["chunks"]
    if not validate_context(chunks):
        return {"answer": NO_CONTEXT_ANSWER, "source": "no_context", "confidence": 0.0}
    try:
        result = get_answer(render_rag_prompt(build_context(chunks), state["question"]))
    except ExternalServiceError:
        return {"answer": LLM_DOWN_ANSWER, "source": "fallback_error", "confidence": 0.0}
    return {"answer": result["answer"], "confidence": result.get("confidence") or 0.0, "source": "rag"}


# --- conditional edges (read state, return the next node's name) ----------------------------
def _after_receive(state: RagState) -> str:
    return END if state.get("source") == "invalid_input" else "route_query"


def _after_route(state: RagState) -> str:
    return {DIRECT: "direct_answer", FALLBACK: "fallback_response", RAG: "retrieve_context",
            TOOL: "select_tool"}[state["route"]]


def _after_select(state: RagState) -> str:
    """search_docs / none = the retrieval path we already have; every other tool is executed."""
    return "retrieve_context" if state["tool_name"] in ("search_docs", "none") else "run_tool"


def build_graph():
    g = StateGraph(RagState)
    g.add_node("receive_query", receive_query)
    g.add_node("route_query", route_query_node)
    g.add_node("direct_answer", direct_answer)
    g.add_node("fallback_response", fallback_response)
    g.add_node("select_tool", select_tool)
    g.add_node("run_tool", run_tool)
    g.add_node("tool_answer", tool_answer)
    g.add_node("retrieve_context", retrieve_context)
    g.add_node("call_llm", call_llm)
    g.add_edge(START, "receive_query")
    g.add_conditional_edges("receive_query", _after_receive, {"route_query": "route_query", END: END})
    g.add_conditional_edges("route_query", _after_route, {
        "direct_answer": "direct_answer", "fallback_response": "fallback_response",
        "retrieve_context": "retrieve_context", "select_tool": "select_tool"})
    g.add_conditional_edges("select_tool", _after_select, {"retrieve_context": "retrieve_context", "run_tool": "run_tool"})
    g.add_edge("run_tool", "tool_answer")
    g.add_edge("tool_answer", END)
    g.add_edge("retrieve_context", "call_llm")
    g.add_edge("direct_answer", END)
    g.add_edge("fallback_response", END)
    g.add_edge("call_llm", END)
    return g.compile()


rag_graph = build_graph()


def run_graph(question: str, top_k: int = 4) -> dict:
    started = time.perf_counter()
    final = rag_graph.invoke({"question": question, "top_k": top_k, "trace": [], "timings": {}})
    timings = {**final.get("timings", {}), "total_ms": round((time.perf_counter() - started) * 1000, 1)}
    logger.info("graph_done route=%s source=%s trace=%s timings=%s", final.get("route"), final.get("source"),
                final.get("trace"), timings)
    return {"question": final.get("question", question), "answer": final.get("answer"),
            "confidence": final.get("confidence", 0.0), "source": final.get("source"),
            "retrieved_chunks": final.get("chunks", []), "route": final.get("route", "invalid"), "timings": timings,
            "graph": {"trace": final.get("trace", []), "query_type": final.get("query_type"),
                      "route_reason": final.get("route_reason"), "routed_by": final.get("routed_by")},
            **({"tool": {"name": final["tool_name"], "arguments": final.get("tool_args"),
                         "decided_by": final.get("tool_decided_by"), **final.get("tool_result", {})}}
               if final.get("tool_name") else {})}
