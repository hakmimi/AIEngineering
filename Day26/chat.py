"""Multi-turn chat: Query -> Memory -> (rewrite follow-up) -> Retrieval -> LLM -> Response -> save turn."""
import logging
import re

from errors import ExternalServiceError
from llm import get_structured
from memory import memory, validate_session_id
from prompts import render_rewrite_prompt
from rag import get_rag_answer
from router import SKIP, route_query

logger = logging.getLogger(__name__)

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {"question": {"type": "string"}},
    "required": ["question"],
    "additionalProperties": False,
}
_REFERENCE = re.compile(r"\b(it|its|they|them|their|there|that|this|those|these|he|she|another|other|also|more|else)\b"
                        r"|^(and|what about|how about)\b", re.I)
_SHORT_FOLLOWUP_WORDS = 6


def needs_rewrite(question: str, history: str) -> bool:
    """Only spend an LLM call when there IS history and the question looks context-dependent."""
    if not history:
        return False
    return len(question.split()) <= _SHORT_FOLLOWUP_WORDS or bool(_REFERENCE.search(question))


def rewrite_question(question: str, history: str) -> str:
    """Make a follow-up standalone ("What about its beaches?" -> "What about Tel Aviv's beaches?"). Fails safe."""
    try:
        rewritten = get_structured(render_rewrite_prompt(history, question), REWRITE_SCHEMA, "rewrite")["question"].strip()
        return rewritten or question
    except ExternalServiceError:
        logger.warning("rewrite_failed - using the original question")
        return question


def chat(session_id: str, question: str, top_k: int = 4) -> dict:
    validate_session_id(session_id)
    question = (question or "").strip()
    history = memory.format_for_prompt(session_id)
    turns_before = len(memory.get_history(session_id)) // 2

    standalone = question
    if route_query(question, top_k).name != SKIP and needs_rewrite(question, history):
        standalone = rewrite_question(question, history)
    logger.info("chat session=%s turns=%s rewritten=%s history_chars=%s",
                session_id, turns_before, standalone != question, len(history))

    result = get_rag_answer(standalone, top_k, None, history)
    result["question"] = question
    result["session"] = {"id": session_id, "turns_before": turns_before,
                         "standalone_question": standalone, "used_memory": bool(history)}
    if result.get("answer"):
        memory.add_turn(session_id, question, result["answer"])
    return result
