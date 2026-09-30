"""The complete Day 14 system in one entry point.

    Query -> Session/Memory -> Decision (rules) -> Tool  OR  Retrieval -> LLM -> Response -> Memory

Only cheap, deterministic rules pick tools here (no extra LLM call per request); the LLM-driven tool
choice from Day 11 stays available on /ask/tools. Everything else reuses the tested modules.
"""
import logging

from chat import chat
from memory import memory, validate_session_id
from router import CLARIFY, SKIP, route_query
from tool_agent import rule_decision, run_with_tools

logger = logging.getLogger(__name__)


def ask(session_id: str, question: str, top_k: int = 4) -> dict:
    validate_session_id(session_id)
    question = (question or "").strip()
    route = route_query(question, top_k)

    decision = rule_decision(question) if route.name not in (SKIP, CLARIFY) else None
    if decision:
        logger.info("assistant path=tool tool=%s session=%s", decision.tool, session_id)
        result = run_with_tools(question, top_k)
        result["session"] = {"id": session_id, "used_memory": False}
        if result.get("answer"):
            memory.add_turn(session_id, question, str(result["answer"]))
        return result

    logger.info("assistant path=chat route=%s session=%s", route.name, session_id)
    return chat(session_id, question, top_k)
