"""Day 15: the RAG pipeline rebuilt as a LangGraph workflow.

    START -> receive_query -> retrieve_context -> call_llm -> END

Why a graph instead of three function calls? A graph makes the flow explicit data (nodes + edges),
carries one shared *state* between steps, and later lets us add branches, retries and persistence
(Days 16-19) without rewriting the steps. Each node is still a plain function `state -> partial update`.
"""
import logging
import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from errors import ExternalServiceError
from llm import get_answer
from prompts import LLM_DOWN_ANSWER, NO_CONTEXT_ANSWER, render_rag_prompt
from rag import build_context, validate_context
from retrieval import get_relevant_chunks

logger = logging.getLogger(__name__)


class RagState(TypedDict, total=False):
    """Everything that travels between nodes. Keys are added as the workflow progresses."""
    question: str
    top_k: int
    chunks: list[dict]
    answer: str
    confidence: float
    source: str                                  # rag | no_context | fallback_error | invalid_input
    trace: Annotated[list[str], operator.add]    # reducer: each node APPENDS instead of overwriting
    timings: Annotated[dict, lambda old, new: {**(old or {}), **new}]  # reducer: merge per-node timings


def timed(name: str):
    """Decorator: record wall-clock ms for a node into state['timings'] and log it."""
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
    """Normalise the incoming question (strip, collapse whitespace). Nothing else - no I/O here."""
    question = " ".join((state.get("question") or "").split())
    if not question:
        return {"question": "", "answer": "Please provide a question.", "source": "invalid_input", "chunks": []}
    return {"question": question, "top_k": state.get("top_k") or 4}


@timed("retrieve_context")
def retrieve_context(state: RagState) -> dict:
    return {"chunks": get_relevant_chunks(state["question"], state["top_k"])}


@timed("call_llm")
def call_llm(state: RagState) -> dict:
    """The LLM is one node, not the system: it only runs when retrieval produced usable context."""
    chunks = state["chunks"]
    if not validate_context(chunks):
        return {"answer": NO_CONTEXT_ANSWER, "source": "no_context", "confidence": 0.0}
    try:
        result = get_answer(render_rag_prompt(build_context(chunks), state["question"]))
    except ExternalServiceError:
        return {"answer": LLM_DOWN_ANSWER, "source": "fallback_error", "confidence": 0.0}
    return {"answer": result["answer"], "confidence": result.get("confidence") or 0.0, "source": "rag"}


def _after_receive(state: RagState) -> str:
    """Conditional edge: an invalid question ends the run immediately (cheapest possible path)."""
    return END if state.get("source") == "invalid_input" else "retrieve_context"


def build_graph():
    graph = StateGraph(RagState)
    graph.add_node("receive_query", receive_query)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("call_llm", call_llm)
    graph.add_edge(START, "receive_query")
    graph.add_conditional_edges("receive_query", _after_receive, {"retrieve_context": "retrieve_context", END: END})
    graph.add_edge("retrieve_context", "call_llm")
    graph.add_edge("call_llm", END)
    return graph.compile()


rag_graph = build_graph()


def run_graph(question: str, top_k: int = 4) -> dict:
    """Entry point used by FastAPI: invoke the graph and shape the same response fields as /rag."""
    started = time.perf_counter()
    final = rag_graph.invoke({"question": question, "top_k": top_k, "trace": [], "timings": {}})
    timings = {**final.get("timings", {}), "total_ms": round((time.perf_counter() - started) * 1000, 1)}
    logger.info("graph_done source=%s trace=%s timings=%s", final.get("source"), final.get("trace"), timings)
    return {"question": final.get("question", question), "answer": final.get("answer"),
            "confidence": final.get("confidence", 0.0), "source": final.get("source"),
            "retrieved_chunks": final.get("chunks", []), "route": "graph", "timings": timings,
            "graph": {"trace": final.get("trace", [])}}
