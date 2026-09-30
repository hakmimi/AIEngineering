"""Retry policy for calls to external services (embeddings / LLM).

Two retry layers exist on purpose:
  1. the OpenAI SDK retries raw HTTP failures (max_retries) - invisible to us;
  2. this app-level retry (tenacity) retries a whole *operation* (e.g. a call that came back as invalid
     JSON) with exponential backoff, logs every retry, and gives up fast on non-retryable errors.
Retrying multiplies latency, so attempts are capped and only ExternalServiceError(retryable=True) retries.
"""
import logging

from tenacity import AsyncRetrying, RetryCallState, Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from config import settings
from errors import ExternalServiceError

logger = logging.getLogger(__name__)


def _should_retry(exc: BaseException) -> bool:
    return isinstance(exc, ExternalServiceError) and exc.retryable


def _retry_kwargs(label: str, attempts: int | None, base_delay: float | None) -> dict:
    def before_sleep(state: RetryCallState) -> None:
        logger.warning("retrying label=%s attempt=%s/%s next_wait_s=%.2f error=%s", label, state.attempt_number,
                       attempts or settings.retry_attempts, state.next_action.sleep, state.outcome.exception())

    return {"stop": stop_after_attempt(attempts or settings.retry_attempts),
            "wait": wait_exponential(multiplier=settings.retry_base_delay if base_delay is None else base_delay, max=8),
            "retry": retry_if_exception(_should_retry), "before_sleep": before_sleep, "reraise": True}


async def aretry_call(fn, *args, label: str = "call", attempts: int | None = None, base_delay: float | None = None, **kwargs):
    """Async twin of retry_call: the backoff waits with asyncio.sleep, so other requests keep running while this one waits."""
    return await AsyncRetrying(**_retry_kwargs(label, attempts, base_delay))(fn, *args, **kwargs)


def retry_call(fn, *args, label: str = "call", attempts: int | None = None, base_delay: float | None = None, **kwargs):
    """Call fn(*args, **kwargs); on a retryable ExternalServiceError wait 1x, 2x, 4x... base_delay and retry."""
    def before_sleep(state: RetryCallState) -> None:
        logger.warning("retrying label=%s attempt=%s/%s next_wait_s=%.2f error=%s", label, state.attempt_number,
                       attempts or settings.retry_attempts, state.next_action.sleep, state.outcome.exception())

    retrying = Retrying(
        stop=stop_after_attempt(attempts or settings.retry_attempts),
        wait=wait_exponential(multiplier=settings.retry_base_delay if base_delay is None else base_delay, max=8),
        retry=retry_if_exception(_should_retry),
        before_sleep=before_sleep,
        reraise=True,          # after the last attempt the original error surfaces (-> fallback path)
    )
    return retrying(fn, *args, **kwargs)
