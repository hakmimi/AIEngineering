import logging

from openai import OpenAIError

from config import settings
from errors import ExternalServiceError
from openai_client import get_client, is_retryable

logger = logging.getLogger(__name__)


def get_embedding(text: str) -> list[float]:
    client = get_client()
    try:
        response = client.embeddings.create(model=settings.embedding_model, input=text)
        return response.data[0].embedding
    except OpenAIError as exc:
        logger.error("embedding_call_failed type=%s", type(exc).__name__)
        raise ExternalServiceError(retryable=is_retryable(exc)) from exc
