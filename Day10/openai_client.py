"""Single place that builds the OpenAI client (was duplicated in llm.py and embeddings.py)."""
from openai import OpenAI

from config import settings
from errors import ConfigurationError

_client: OpenAI | None = None


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
