"""RAG orchestration: route -> retrieve -> validate -> prompt -> LLM.

Each stage is its own small function; get_rag_answer only wires them together.
"""
import logging

from config import settings
from errors import ExternalServiceError
from llm import get_answer
from prompts import LLM_DOWN_ANSWER, NO_CONTEXT_ANSWER, RAG_PROMPT, render_rag_prompt  # noqa: F401 (re-exported)
from retrieval import get_relevant_chunks
from router import CLARIFY, RAG_COMPLEX, SKIP, Route, route_query
from timing import StepTimer
from usage import estimate_tokens

logger = logging.getLogger(__name__)


def build_context(chunks: list[dict]) -> str:
    """Best-first "[doc:chunk|topic] text" lines (topic gives the model the subject), within the budget."""
    lines = [f"[{c['doc_id']}:{c['chunk_id']}|{c.get('topic') or 'n/a'}] {c['text']}" for c in chunks]
    budget = settings.max_context_tokens
    if budget:                                  # keep whole chunks, best first; never cut one in half
        kept, used = [], 0
        for line in lines:
            tokens = estimate_tokens(line)
            if kept and used + tokens > budget:
                break
            kept.append(line)
            used += tokens
        lines = kept
    return "\n".join(lines)[:settings.max_context_chars]


def validate_context(chunks: list[dict]) -> bool:
    """Gate before the LLM call: enough chunks AND the best one is relevant enough."""
    return len(chunks) >= settings.min_context_chunks and chunks[0]["score"] >= settings.retrieval_threshold


def build_response(question: str, answer: str, source: str, route: str, timer: StepTimer,
                   chunks=(), confidence: float = 0.0, score=None, extra: dict | None = None) -> dict:
    """The one place that shapes the API result and logs the finished request."""
    timings = timer.report()
    logger.info("request route=%s source=%s timings=%s slowest=%s", route, source, timings, timer.slowest())
    if timings["total_ms"] > settings.slow_request_ms:
        logger.warning("slow_request total_ms=%s slowest_step=%s", timings["total_ms"], timer.slowest())
    return {"question": question, "answer": answer, "confidence": confidence, "score": score,
            "retrieved_chunks": list(chunks), "source": source, "route": route, "timings": timings,
            **(extra or {})}


def _answer_directly(question: str, route: Route, timer: StepTimer) -> dict:
    """Skip/clarify routes: canned answer, zero API calls."""
    source = "smalltalk" if route.name == SKIP else "invalid_input"
    return build_response(question, route.direct_answer, source, route.name, timer)


def _answer_from_context(question: str, route: Route, timer: StepTimer, filters: dict | None = None,
                         history: str = "") -> dict:
    with timer.step("retrieval"):
        chunks = get_relevant_chunks(question, route.top_k, filters, wide=route.name == RAG_COMPLEX)

    if not validate_context(chunks):
        logger.info("decision=blocked_no_context best=%.3f", chunks[0]["score"] if chunks else 0.0)
        return build_response(question, NO_CONTEXT_ANSWER, "no_context", route.name, timer)

    with timer.step("prompt"):
        prompt = render_rag_prompt(build_context(chunks), question, history)

    try:
        with timer.step("llm"):
            llm = get_answer(prompt)
    except ExternalServiceError:
        logger.error("decision=fallback_llm_unavailable")
        return build_response(question, LLM_DOWN_ANSWER, "fallback_error", route.name, timer, chunks)

    return build_response(question, llm.get("answer"), "rag", route.name, timer, chunks,
                          llm.get("confidence"), llm.get("score"))


def get_rag_answer(question: str, top_k: int = 4, filters: dict | None = None, history: str = "") -> dict:
    timer = StepTimer()
    question = (question or "").strip()

    with timer.step("routing"):
        route = route_query(question, top_k)
    logger.info("decision=route name=%s reason=%s top_k=%s", route.name, route.reason, route.top_k)

    if route.name in (SKIP, CLARIFY):
        return _answer_directly(question, route, timer)
    return _answer_from_context(question, route, timer, filters, history)
