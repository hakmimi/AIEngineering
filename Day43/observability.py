"""Structured logging + request tracing.

Every log line is one JSON object (LOG_FORMAT=text gives a readable line for local debugging):

    {"ts": "...", "level": "INFO", "logger": "graph", "event": "graph_node", "request_id": "a1b2c3d4e5f6",
     "node": "retrieve_context", "ms": 412.3}

* `request_id` comes from a ContextVar set by the HTTP middleware (header `X-Request-ID` is honoured, otherwise
  generated) and is attached to EVERY record by a logging filter - so one grep reconstructs one request.
* `log_event(logger, "name", key=value, ...)` emits proper fields for JSON *and* a readable `name key=value` message.
* User text is redacted by default (privacy): set LOG_USER_TEXT=1 while debugging to see it.
"""
import contextvars
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
decision_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("decision_id", default="-")   # set while a decision is being made

_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "event", "fields"}


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def redact(text: str | None) -> str:
    """User-provided text is only logged when LOG_USER_TEXT=1; otherwise just its length."""
    if text is None:
        return "-"
    return text if os.getenv("LOG_USER_TEXT") == "1" else f"<{len(text)} chars>"


def summarize(value, limit: int = 120) -> str:
    """Short, single-line representation of a tool argument/output for logs."""
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"...(+{len(text) - limit})"


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields) -> None:
    """Emit `event key=value ...` as text AND as structured fields for the JSON formatter."""
    message = event + "".join(f" {k}={summarize(v) if isinstance(v, (dict, list)) else v}" for k, v in fields.items())
    logger.log(level, message, extra={"event": event, "fields": fields})


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.decision_id = decision_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", None) or record.getMessage().split(" ", 1)[0],
            "request_id": getattr(record, "request_id", "-"),
        }
        if getattr(record, "decision_id", "-") != "-":
            payload["decision_id"] = record.decision_id
        fields = getattr(record, "fields", None)
        if fields:
            payload.update({k: v for k, v in fields.items() if k not in payload})
        else:
            payload["msg"] = record.getMessage()      # legacy free-text lines keep their full message
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.request_id = getattr(record, "request_id", "-")
        return super().format(record)


def configure_logging(level: int = logging.INFO, stream=None, fmt: str | None = None) -> None:
    """Idempotent: replaces the root handler so repeated calls (tests, reload) don't duplicate lines."""
    fmt = fmt or os.getenv("LOG_FORMAT", "json")
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else
                         TextFormatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s - %(message)s"))
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_app_handler", False):
            root.removeHandler(existing)
    handler._app_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "openai", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)      # request-level logging is ours, not the libraries'
