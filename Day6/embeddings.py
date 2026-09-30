from config import settings
from openai import OpenAI,OpenAIError
import logging
from errors import ConfigurationError, ExternalServiceError

logger = logging.getLogger(__name__)
if not settings.openai_api_key:
    client = None
else:
    client = OpenAI(api_key = settings.openai_api_key,
                    timeout = settings.openai_timeout_seconds,
                    max_retries= settings.openai_max_retries)
    

def get_embedding(text : str) ->list[float]:
    if client is None:
        raise ConfigurationError("OPENAI_API_KEY is not configured")
    try:
        response = client.embeddings.create(
            model=settings.embedding_model,
            input=text
        )
        return(response.data[0].embedding)
    except OpenAIError as exc:
        logger.exception("OpenAI embedding request failed")
        raise ExternalServiceError() from exc
    