"""Day 29 skeleton: only what the design needs to be runnable - health and input validation.

Decision endpoints (baseline, AI, audit) arrive on later days; see docs/DESIGN.md for the plan.
"""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ai_decision import decide_ai
from decision_engine import decide_baseline
from decision_graph import run_decision_graph
from errors import AppError
from explanations import template_explanation
from observability import configure_logging, log_event, new_request_id, request_id_var
from schemas import Transaction
from tool_pipeline import decide_with_tools

configure_logging()
logger = logging.getLogger("http")
app = FastAPI(title="Payment Routing Decision Agent")


@app.middleware("http")
async def request_context(request: Request, call_next):
    token = request_id_var.set(request.headers.get("x-request-id") or new_request_id())
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id_var.get()
        return response
    finally:
        request_id_var.reset(token)


@app.exception_handler(AppError)
def app_error_handler(request: Request, exc: AppError):
    log_event(logger, "app_error", level=logging.WARNING, path=request.url.path, status=exc.status_code, msg=exc.message)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "request_id": request_id_var.get()})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/events/validate")
def validate_event(transaction: Transaction) -> dict:
    """Accept a transaction and echo it back normalised - proves the input contract before any decision logic exists."""
    log_event(logger, "event_validated", transaction_id=transaction.transaction_id, amount=transaction.amount,
              currency=transaction.currency.value, country=transaction.country)
    return {"valid": True, "transaction": transaction.model_dump(mode="json")}


@app.post("/decision/baseline")
def decision_baseline(transaction: Transaction) -> dict:
    """Deterministic decision (no LLM): risk rules -> eligibility -> scoring -> action with reason codes."""
    started = time.perf_counter()
    result = decide_baseline(transaction)
    result.decision.explanation = template_explanation(result.decision)
    return {**result.to_dict(), "latency_ms": round((time.perf_counter() - started) * 1000, 2)}


@app.post("/decision/ai")
def decision_ai(transaction: Transaction) -> dict:
    """Baseline decision + LLM explanation/second opinion. The LLM can only make the outcome safer (route -> manual_review)."""
    return decide_ai(transaction).to_dict()


@app.post("/decision/tools")
def decision_tools(transaction: Transaction) -> dict:
    """Rules over audited tool calls (no LLM). Same decision as /decision/baseline, plus the trace of every lookup."""
    result = decide_with_tools(transaction)
    result.decision.explanation = template_explanation(result.decision)
    return {**result.baseline.to_dict(), "tool_trace": result.trace.calls, "tool_failure": result.tool_failure}


@app.post("/decision")
def decision_graph_endpoint(transaction: Transaction) -> dict:
    """The LangGraph workflow: tools -> rules -> LLM explanation -> controlled final decision (response includes the node trace)."""
    return run_decision_graph(transaction).to_dict()
