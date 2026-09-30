import json
import logging

from openai import OpenAIError

from config import settings
from errors import ExternalServiceError
from openai_client import get_client, is_retryable
from prompts import with_json_schema
from usage import record_usage

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


def _call_model(prompt: str, schema: dict, name: str) -> str:
    """One LLM round-trip; any provider error becomes ExternalServiceError."""
    client = get_client()
    try:
        response = client.responses.create(
            model=settings.llm_model,
            input=with_json_schema(prompt, schema) if settings.json_schema_in_prompt else prompt,
            temperature=0,
            text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
        )
    except OpenAIError as exc:  # timeout, rate limit, connection, ...
        logger.error("llm_call_failed step=%s type=%s", name, type(exc).__name__)
        raise ExternalServiceError(retryable=is_retryable(exc)) from exc
    usage = getattr(response, "usage", None)
    if usage is not None:                      # cost tracking must never break a request
        record_usage("llm", name, settings.llm_model, usage.input_tokens, usage.output_tokens)
    return response.output_text


def get_structured(prompt: str, schema: dict, name: str) -> dict:
    """Generic structured-output call used by every pipeline step. Invalid JSON -> ExternalServiceError."""
    raw = _call_model(prompt, schema, name)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("llm_returned_non_json step=%s", name)
        raise ExternalServiceError("The AI service returned an invalid response", retryable=True) from exc


def get_answer(prompt: str) -> dict:
    """Return {answer, confidence, score}; tolerate a model that ignores the JSON format."""
    raw = _call_model(prompt, ANSWER_SCHEMA, "rag_answer")
    try:
        data = json.loads(raw)
        return {key: data.get(key) for key in ("answer", "confidence", "score")}
    except json.JSONDecodeError:
        logger.warning("llm_returned_non_json step=rag_answer")
        return {"answer": raw, "confidence": 0.5, "score": 0}
