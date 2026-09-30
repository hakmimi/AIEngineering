"""The only place that talks to the LLM: one structured-output call with retry, usage tracking and typed errors."""
import json
import logging

from openai import OpenAIError

from config import settings
from errors import ExternalServiceError
from openai_client import get_async_client, get_client, is_retryable
from resilience import aretry_call, retry_call
from usage import record_usage

logger = logging.getLogger(__name__)


def _call_once(prompt: str, schema: dict, name: str) -> dict:
    client = get_client()
    try:
        response = client.responses.create(
            model=settings.llm_model, input=prompt, temperature=0,
            text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
        )
    except OpenAIError as exc:
        logger.error("llm_call_failed step=%s type=%s", name, type(exc).__name__)
        raise ExternalServiceError(retryable=is_retryable(exc)) from exc
    usage = getattr(response, "usage", None)
    if usage is not None:
        record_usage("llm", name, settings.llm_model, usage.input_tokens, usage.output_tokens)
    try:
        return json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise ExternalServiceError("The AI service returned an invalid response", retryable=True) from exc


def get_structured(prompt: str, schema: dict, name: str) -> dict:
    """Structured JSON from the model, retried on transient failures. Raises ExternalServiceError when it cannot deliver."""
    return retry_call(_call_once, prompt, schema, name, label=name)


async def _acall_once(prompt: str, schema: dict, name: str) -> dict:
    client = get_async_client()
    try:
        response = await client.responses.create(
            model=settings.llm_model, input=prompt, temperature=0,
            text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
        )
    except OpenAIError as exc:
        logger.error("llm_call_failed step=%s type=%s", name, type(exc).__name__)
        raise ExternalServiceError(retryable=is_retryable(exc)) from exc
    usage = getattr(response, "usage", None)
    if usage is not None:
        record_usage("llm", name, settings.llm_model, usage.input_tokens, usage.output_tokens)
    try:
        return json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise ExternalServiceError("The AI service returned an invalid response", retryable=True) from exc


async def aget_structured(prompt: str, schema: dict, name: str) -> dict:
    """Async twin of get_structured: awaits the network call instead of blocking a thread while the model thinks."""
    return await aretry_call(_acall_once, prompt, schema, name, label=name)
