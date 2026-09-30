import json
import logging

from openai import OpenAIError

from config import settings
from errors import ExternalServiceError
from openai_client import get_client
from prompts import with_json_schema

logger = logging.getLogger(__name__)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "score": {"type": ["number", "null"]},
    },
    "required": ["answer", "confidence", "score"],
    "additionalProperties": False,
}


def _call_model(prompt: str) -> str:
    """One LLM round-trip; any provider error becomes ExternalServiceError."""
    client = get_client()
    try:
        response = client.responses.create(
            model=settings.llm_model,
            input=with_json_schema(prompt, ANSWER_SCHEMA),
            temperature=0,
            text={"format": {"type": "json_schema", "name": "rag_answer",
                             "schema": ANSWER_SCHEMA, "strict": True}},
        )
    except OpenAIError as exc:  # timeout, rate limit, connection, ...
        logger.error("llm_call_failed type=%s", type(exc).__name__)
        raise ExternalServiceError() from exc
    return response.output_text


def get_answer(prompt: str) -> dict:
    """Return {answer, confidence, score}; tolerate a model that ignores the JSON format."""
    raw = _call_model(prompt)
    try:
        data = json.loads(raw)
        return {key: data.get(key) for key in ("answer", "confidence", "score")}
    except json.JSONDecodeError:
        logger.warning("llm_returned_non_json")
        return {"answer": raw, "confidence": 0.5, "score": 0}
