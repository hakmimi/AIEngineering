from openai import OpenAI
import json
import logging

from openai import OpenAIError

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
    "required": ["answer", "confidence"],
    "additionalProperties": False,
}

if not settings.openai_api_key:
    client = None
else:
    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )

def get_answer(question : str) -> dict:
    if client is None:
        raise ConfigurationError("OPENAI_API_KEY is not configured")

    prompt = f"""
        You are a helpful AI assistant.
        Answer the user's question and return only valid JSON matching this schema:
        {json.dumps(ANSWER_SCHEMA)}
        Question: {question}
        """

    try:
        # Original code depended only on prompt instructions for JSON. Structured output is
        # preferred when the installed SDK supports it, with a prompt-only fallback.
        try:
            response = client.responses.create(
                model=settings.llm_model,
                input=prompt,
                temperature=0,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "rag_answer",
                        "schema": ANSWER_SCHEMA,
                        "strict": True,
                    }
                },
            )
        except TypeError:
            response = client.responses.create(
                model=settings.llm_model,
                input=prompt,
                temperature=0,
            )
    except OpenAIError as exc:
        logger.exception("OpenAI LLM request failed")
        raise ExternalServiceError() from exc

    text_output = response.output_text
   
    
    try:
        data =  json.loads(text_output)
        return  {
                 "answer":data.get("answer"),
                 "confidence" :data.get("confidence"),
                 "score" : data.get('score')
                    }
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON output")
        return {
                "answer":text_output,
                "confidence" : 0.5,
                "score" : 0
   
        }
    
    

