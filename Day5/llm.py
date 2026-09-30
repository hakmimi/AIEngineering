import json
import logging

from openai import OpenAI, OpenAIError

from config import settings
from errors import ConfigurationError, ExternalServiceError

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

client = None
if settings.openai_api_key:
    client = OpenAI(api_key=settings.openai_api_key,
                    timeout=settings.openai_timeout_seconds,
                    max_retries=settings.openai_max_retries)


def get_answer(prompt: str) -> dict:
    """Call the LLM; raises ExternalServiceError on any provider failure/timeout."""
    if client is None:
        raise ConfigurationError("OPENAI_API_KEY is not configured")

    full_prompt = f"{prompt}\n\nReturn only valid JSON matching this schema:\n{json.dumps(ANSWER_SCHEMA)}"
    try:
        response = client.responses.create(
            model=settings.llm_model,
            input=full_prompt,
            temperature=0,
            text={"format": {"type": "json_schema", "name": "rag_answer",
                             "schema": ANSWER_SCHEMA, "strict": True}},
        )
    except OpenAIError as exc:  # includes APITimeoutError, RateLimitError, APIConnectionError
        logger.error("llm_call_failed type=%s", type(exc).__name__)
        raise ExternalServiceError() from exc

    try:
        data = json.loads(response.output_text)
        return {"answer": data.get("answer"),
                "confidence": data.get("confidence"),
                "score": data.get("score")}
    except json.JSONDecodeError:
        logger.warning("llm_returned_non_json")
        return {"answer": response.output_text, "confidence": 0.5, "score": 0}
