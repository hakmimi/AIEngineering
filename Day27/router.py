"""Rule-based decision layer: runs BEFORE any embedding or LLM call (both cost money + latency)."""
import re
from dataclasses import dataclass

from config import settings

SKIP = "skip"                # answer directly, no retrieval, no LLM
CLARIFY = "clarify"          # input too poor to search with
RAG_SIMPLE = "rag_simple"    # short factual question -> small context
RAG_COMPLEX = "rag_complex"  # multi-part / reasoning question -> larger context

_SMALLTALK = {
    r"^(hi|hello|hey|shalom|good (morning|evening|afternoon))\b": "Hello! Ask me a question about Israel.",
    r"^(thanks|thank you|thx|toda)\b": "You're welcome!",
    r"^(bye|goodbye|see you)\b": "Goodbye!",
}
_COMPLEX_MARKERS = re.compile(r"\b(compare|difference|versus|vs|explain|relationship|between|both|several|and)\b", re.I)


@dataclass(frozen=True)
class Route:
    name: str
    top_k: int
    reason: str
    direct_answer: str | None = None


def route_query(question: str, requested_top_k: int) -> Route:
    text = (question or "").strip()
    words = re.findall(r"\w+", text)

    for pattern, reply in _SMALLTALK.items():
        if re.match(pattern, text.lower()) and len(words) <= 4:
            return Route(SKIP, 0, "smalltalk", reply)

    if len(words) < settings.min_query_words:
        return Route(CLARIFY, 0, "too_short", "Could you rephrase your question with a bit more detail?")

    if len(words) > settings.complex_query_words or _COMPLEX_MARKERS.search(text):
        return Route(RAG_COMPLEX, min(max(requested_top_k, 6), settings.max_top_k), "complex_query")

    return Route(RAG_SIMPLE, min(requested_top_k, 3), "simple_query")
