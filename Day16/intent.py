"""Query classification for the graph router: rules by default, optional LLM classifier.

Both return the same Decision, so the graph doesn't care who decided. The LLM classifier fails safe
(falls back to the rules) - a router that can crash the request would defeat its purpose.
"""
import logging
from dataclasses import dataclass

from config import settings
from errors import ExternalServiceError
from llm import get_structured
from prompts import render_intent_prompt
from router import CLARIFY, RAG_COMPLEX, SKIP, route_query

logger = logging.getLogger(__name__)

DIRECT, RAG, FALLBACK = "direct", "rag", "fallback"
DIRECT_DEFAULT = "Hello! Ask me a question about Israel."
FALLBACK_ANSWER = "Could you rephrase your question with a bit more detail?"

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": [DIRECT, RAG, FALLBACK]},
        "query_type": {"type": "string", "enum": ["simple", "complex"]},
        "reason": {"type": "string"},
    },
    "required": ["route", "query_type", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Decision:
    route: str            # direct | rag | fallback
    query_type: str       # simple | complex
    reason: str
    by: str               # rule | llm
    answer: str | None = None   # canned text for direct/fallback


def rule_classify(question: str) -> Decision:
    r = route_query(question, 4)
    if r.name == SKIP:
        return Decision(DIRECT, "simple", r.reason, "rule", r.direct_answer)
    if r.name == CLARIFY:
        return Decision(FALLBACK, "simple", r.reason, "rule", r.direct_answer)
    return Decision(RAG, "complex" if r.name == RAG_COMPLEX else "simple", r.reason, "rule")


def llm_classify(question: str) -> Decision:
    try:
        out = get_structured(render_intent_prompt(question), INTENT_SCHEMA, "intent")
    except ExternalServiceError:
        logger.warning("intent_llm_failed - using rules")
        return rule_classify(question)
    answer = {DIRECT: DIRECT_DEFAULT, FALLBACK: FALLBACK_ANSWER}.get(out["route"])
    return Decision(out["route"], out["query_type"], out["reason"], "llm", answer)


def classify(question: str) -> Decision:
    return llm_classify(question) if settings.llm_routing else rule_classify(question)
