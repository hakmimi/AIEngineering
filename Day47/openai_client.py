"""Single place that builds the OpenAI client (was duplicated in llm.py and embeddings.py)."""
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError, OpenAI, RateLimitError

from config import settings
from errors import ConfigurationError

_client: OpenAI | None = None
_async_client: AsyncOpenAI | None = None


def get_client() -> OpenAI:
    """Lazily create one shared client; fail clearly if the key is missing."""
    global _client
    if not settings.openai_api_key:
        raise ConfigurationError("OPENAI_API_KEY is not configured")
    if _client is None:
        _client = OpenAI(api_key=settings.openai_api_key,
                         timeout=settings.openai_timeout_seconds,
                         max_retries=settings.openai_max_retries)
    return _client


def get_async_client() -> AsyncOpenAI:
    """Async twin of get_client(): awaiting a network call frees the event loop for other requests."""
    global _async_client
    if not settings.openai_api_key:
        raise ConfigurationError("OPENAI_API_KEY is not configured")
    if _async_client is None:
        _async_client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds,
                                    max_retries=settings.openai_max_retries)
    return _async_client


def is_retryable(exc: Exception) -> bool:
    """Transient provider failures are worth retrying; auth/validation errors are not."""
    return isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError))
