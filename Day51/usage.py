"""Token + cost tracking.

Each LLM/embedding call reports its token usage (from the provider's response); a per-request tracker
(ContextVar, like the request id) sums them so a request's cost can be logged and returned.

PRICES are USD per 1M tokens and are an *estimate* - check your provider's current price list; override with
the PRICING_JSON env var, e.g. '{"gpt-4.1-mini": {"input": 0.40, "output": 1.60}}'.
"""
import contextvars
import json
import logging
import math
import os
from dataclasses import dataclass, field

from observability import log_event

logger = logging.getLogger(__name__)

PRICES: dict[str, dict[str, float]] = {
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
    **json.loads(os.getenv("PRICING_JSON", "{}")),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    """USD. Unknown model -> 0.0 (and a warning) rather than a crash: cost tracking must never break a request."""
    price = PRICES.get(model)
    if price is None:
        logger.warning("no_price_for_model model=%s", model)
        return 0.0
    return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000


def estimate_tokens(text: str) -> int:
    """Cheap pre-flight estimate (~4 characters per token for English). Used for budgets, not for billing."""
    return math.ceil(len(text) / 4)


@dataclass
class UsageTracker:
    calls: list[dict] = field(default_factory=list)

    def add(self, kind: str, step: str, model: str, input_tokens: int, output_tokens: int = 0) -> None:
        cost = estimate_cost(model, input_tokens, output_tokens)
        self.calls.append({"kind": kind, "step": step, "model": model, "input_tokens": input_tokens,
                           "output_tokens": output_tokens, "cost_usd": cost})

    def summary(self) -> dict:
        llm = [c for c in self.calls if c["kind"] == "llm"]
        emb = [c for c in self.calls if c["kind"] == "embedding"]
        return {
            "llm_calls": len(llm), "embedding_calls": len(emb),
            "llm_input_tokens": sum(c["input_tokens"] for c in llm),
            "llm_output_tokens": sum(c["output_tokens"] for c in llm),
            "embedding_tokens": sum(c["input_tokens"] for c in emb),
            "estimated_cost_usd": round(sum(c["cost_usd"] for c in self.calls), 6),
        }


_tracker: contextvars.ContextVar[UsageTracker | None] = contextvars.ContextVar("usage_tracker", default=None)


def start_tracking() -> tuple[UsageTracker, contextvars.Token]:
    tracker = UsageTracker()
    return tracker, _tracker.set(tracker)


def stop_tracking(token: contextvars.Token) -> None:
    _tracker.reset(token)


def record_usage(kind: str, step: str, model: str, input_tokens: int, output_tokens: int = 0) -> None:
    """Log the call (always) and add it to the current request's tracker (if any)."""
    cost = estimate_cost(model, input_tokens, output_tokens)
    log_event(logger, "llm_usage" if kind == "llm" else "embedding_usage", step=step, model=model,
              input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=round(cost, 8))
    tracker = _tracker.get()
    if tracker is not None:
        tracker.add(kind, step, model, input_tokens, output_tokens)
