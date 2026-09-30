"""Multi-step RAG pipeline: analyze -> retrieve -> extract facts -> compose answer.

Each step is a small function that reads/writes a shared PipelineState (no framework). Steps use
different prompts (prompts.py) and their intermediate outputs are logged and returned as a trace.
"""
import logging
from dataclasses import dataclass, field

from errors import ExternalServiceError
from llm import ANSWER_SCHEMA, get_structured
from prompts import LLM_DOWN_ANSWER, NO_CONTEXT_ANSWER, render_analyze_prompt, render_compose_prompt, render_extract_prompt
from rag import build_context, build_response, validate_context
from retrieval import get_relevant_chunks
from router import CLARIFY, SKIP, route_query
from timing import StepTimer

logger = logging.getLogger(__name__)

ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "search_query": {"type": "string"},
        "intent": {"type": "string", "enum": ["lookup", "comparison", "open"]},
    },
    "required": ["search_query", "intent"],
    "additionalProperties": False,
}
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array", "items": {
            "type": "object",
            "properties": {"tag": {"type": "string"}, "sentence": {"type": "string"}},
            "required": ["tag", "sentence"], "additionalProperties": False}},
    },
    "required": ["facts"],
    "additionalProperties": False,
}


@dataclass
class PipelineState:
    question: str
    top_k: int
    filters: dict | None
    timer: StepTimer
    route_name: str = "rag_simple"
    search_query: str = ""
    intent: str = "open"
    chunks: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)
    answer: str | None = None
    confidence: float = 0.0
    source: str = "multistep"
    trace: list[dict] = field(default_factory=list)
    done: bool = False  # a step sets this to stop the pipeline (safe refusal / failure)

    def record(self, step: str, output) -> None:
        self.trace.append({"step": step, "output": output})
        logger.info("pipeline_step step=%s output=%s", step, output)


# --- steps ---------------------------------------------------------------------------
def analyze(state: PipelineState) -> None:
    """LLM step 1: turn the question into a keyword search query + intent. Degrades to the raw question."""
    try:
        result = get_structured(render_analyze_prompt(state.question), ANALYZE_SCHEMA, "analyze")
        state.search_query = result["search_query"].strip() or state.question
        state.intent = result["intent"]
    except ExternalServiceError:
        logger.warning("analyze_failed - falling back to the raw question")
        state.search_query, state.intent = state.question, "open"
    state.record("analyze", {"search_query": state.search_query, "intent": state.intent})


def retrieve(state: PipelineState) -> None:
    top_k = max(state.top_k, 6) if state.intent == "comparison" else state.top_k
    state.chunks = get_relevant_chunks(state.search_query, top_k, state.filters)
    if not state.chunks and state.search_query != state.question:
        # the rewrite can lose information; retry once with the user's own words
        state.chunks = get_relevant_chunks(state.question, top_k, state.filters)
    state.record("retrieve", [f"{c['doc_id']}:{c['chunk_id']}|{c.get('topic')}@{c['score']:.2f}" for c in state.chunks])
    if not validate_context(state.chunks):
        state.answer, state.source, state.done = NO_CONTEXT_ANSWER, "no_context", True


def extract(state: PipelineState) -> None:
    """LLM step 2: keep only the sentences that matter, so the answer step sees less noise."""
    result = get_structured(render_extract_prompt(build_context(state.chunks), state.question),
                            EXTRACT_SCHEMA, "extract")
    state.facts = result["facts"]
    state.record("extract", [f"{f['tag']}: {f['sentence'][:60]}" for f in state.facts])
    if not state.facts:
        state.answer, state.source, state.done = NO_CONTEXT_ANSWER, "no_context", True


def compose(state: PipelineState) -> None:
    """LLM step 3: write the final answer from the extracted facts only."""
    facts = "\n".join(f"[{f['tag']}] {f['sentence']}" for f in state.facts)
    result = get_structured(render_compose_prompt(facts, state.question), ANSWER_SCHEMA, "compose")
    state.answer, state.confidence = result["answer"], result["confidence"]
    state.record("compose", state.answer[:80])


STEPS = [analyze, retrieve, extract, compose]


# --- orchestration -------------------------------------------------------------------
def run_pipeline(question: str, top_k: int = 4, filters: dict | None = None) -> dict:
    timer = StepTimer()
    question = (question or "").strip()
    with timer.step("routing"):
        route = route_query(question, top_k)

    if route.name in (SKIP, CLARIFY):  # rule layer still short-circuits: zero API calls
        source = "smalltalk" if route.name == SKIP else "invalid_input"
        return build_response(question, route.direct_answer, source, route.name, timer)

    state = PipelineState(question, route.top_k, filters, timer, route_name=route.name)
    try:
        for step in STEPS:
            with timer.step(step.__name__):
                step(state)
            if state.done:
                break
    except ExternalServiceError:
        logger.error("pipeline_failed at=%s", state.trace[-1]["step"] if state.trace else "start")
        state.answer, state.source = LLM_DOWN_ANSWER, "fallback_error"

    extra = {"pipeline": {"intent": state.intent, "search_query": state.search_query,
                          "facts": state.facts, "trace": state.trace}}
    return build_response(question, state.answer, state.source, state.route_name, timer,
                          state.chunks, state.confidence, None, extra)
