"""Day 29 skeleton: only what the design needs to be runnable - health and input validation.

Decision endpoints (baseline, AI, audit) arrive on later days; see docs/DESIGN.md for the plan.
"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ai_decision import decide_ai
from audit import audit_store
from config import settings
from decision_engine import decide_baseline
from decision_graph import arun_decision_graph, run_decision_graph
from errors import AppError, ConfigurationError
from explanations import template_explanation
from jobs import JobQueue, JobStore
from modes import decide_with_mode
from observability import configure_logging, log_event, new_request_id, request_id_var
from openai_client import get_async_client, get_client
from schemas import Transaction
from security import rate_limit, require_api_key
from tool_pipeline import decide_with_tools
from version import AGENT_VERSION, CHANGELOG

configure_logging()
logger = logging.getLogger("http")
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warm up the LLM clients at startup: creating one (TLS context, connection pool) takes ~0.3 s and, done lazily inside an async
    request, would freeze the event loop for every other request. Missing key = nothing to warm (the API still serves rule paths)."""
    try:
        get_client()
        get_async_client()
    except ConfigurationError:
        pass
    log_event(logger, "active_config", **settings.snapshot())        # which configuration is this process running with?
    app.state.jobs = JobQueue(JobStore(settings.jobs_db_path), arun_decision_graph)
    await app.state.jobs.start()                         # workers + recovery of jobs left unfinished by a previous run
    try:
        yield
    finally:
        await app.state.jobs.stop()


app = FastAPI(title="Payment Routing Decision Agent", lifespan=lifespan)


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


PROTECTED = [Depends(require_api_key), Depends(rate_limit)]


@app.post("/decision/baseline", dependencies=PROTECTED)
def decision_baseline(transaction: Transaction) -> dict:
    """Deterministic decision (no LLM): risk rules -> eligibility -> scoring -> action with reason codes."""
    started = time.perf_counter()
    result = decide_baseline(transaction)
    result.decision.explanation = template_explanation(result.decision)
    return {**result.to_dict(), "latency_ms": round((time.perf_counter() - started) * 1000, 2)}


@app.post("/decision/ai", dependencies=PROTECTED)
def decision_ai(transaction: Transaction) -> dict:
    """Baseline decision + LLM explanation/second opinion. The LLM can only make the outcome safer (route -> manual_review)."""
    return decide_ai(transaction).to_dict()


@app.post("/decision/tools", dependencies=PROTECTED)
def decision_tools(transaction: Transaction) -> dict:
    """Rules over audited tool calls (no LLM). Same decision as /decision/baseline, plus the trace of every lookup."""
    result = decide_with_tools(transaction)
    result.decision.explanation = template_explanation(result.decision)
    return {**result.baseline.to_dict(), "tool_trace": result.trace.calls, "tool_failure": result.tool_failure}


@app.post("/decision", dependencies=PROTECTED)
def decision_graph_endpoint(transaction: Transaction) -> dict:
    """The LangGraph workflow: tools -> rules -> LLM explanation -> controlled final decision (response includes the node trace)."""
    return run_decision_graph(transaction).to_dict()


@app.get("/decision/audit/{decision_id}", dependencies=PROTECTED)
def get_audit(decision_id: str) -> dict:
    """The full audit record of one decision (404 if unknown) plus a tamper check."""
    record = audit_store.get(decision_id)
    return {"record": record.model_dump(mode="json"), "integrity_ok": audit_store.verify(decision_id)}


@app.get("/decision/audit", dependencies=PROTECTED)
def find_audits(transaction_id: str) -> dict:
    """All decision ids recorded for a transaction id."""
    return {"transaction_id": transaction_id, "decision_ids": audit_store.for_transaction(transaction_id)}


@app.post("/decision/async", dependencies=PROTECTED)
async def decision_async(transaction: Transaction) -> dict:
    """Same decision as POST /decision, but the LLM calls are awaited (AsyncOpenAI + graph.ainvoke): one worker serves many
    requests while they wait on the model. The sync endpoint already scales through FastAPI's thread pool; this one does it
    with far fewer threads."""
    return (await arun_decision_graph(transaction)).to_dict()


@app.post("/decision/async-naive", dependencies=PROTECTED)
async def decision_async_naive(transaction: Transaction) -> dict:
    """ANTI-PATTERN kept for the benchmark only: `async def` that calls the blocking graph directly. It blocks the event loop,
    so every other request (even /health) waits. Do not use."""
    return run_decision_graph(transaction).to_dict()


class JobRequest(BaseModel):
    transaction: Transaction
    simulate_delay_s: float = Field(default=0, ge=0, le=30, description="demo only: pretend the model call takes this long")


def _queue(request: Request) -> JobQueue:
    queue = getattr(request.app.state, "jobs", None)
    if queue is None:
        raise AppError("the job queue is not running", status_code=503)
    return queue


@app.post("/jobs", status_code=202, dependencies=PROTECTED)
def submit_job(body: JobRequest, request: Request, response: Response) -> dict:
    """Queue a transaction for background decisioning and return immediately (202). The same transaction id is idempotent."""
    if body.simulate_delay_s and not settings.allow_simulated_delay:
        raise AppError("simulate_delay_s is disabled (set ALLOW_SIMULATED_DELAY=1 for demos)", status_code=422)
    job, is_new = _queue(request).submit(body.transaction, body.simulate_delay_s)
    if not is_new:
        response.status_code = 200
    return {"job_id": job.job_id, "status": job.status.value, "status_url": f"/status/{job.job_id}", "duplicate": not is_new}


@app.get("/status/{job_id}", dependencies=PROTECTED)
def job_status(job_id: str, request: Request) -> dict:
    return _queue(request).store.get(job_id).to_dict()


@app.get("/jobs", dependencies=PROTECTED)
def queue_stats(request: Request) -> dict:
    return _queue(request).stats()


@app.post("/decide", dependencies=PROTECTED)
def decide(transaction: Transaction, mode: str | None = None) -> dict:
    """One entry point for every mode. `?mode=baseline|ai|graph` (default from config; other modes must be enabled in allowed_modes)."""
    return decide_with_mode(transaction, mode)


@app.get("/config", dependencies=PROTECTED)
def show_config() -> dict:
    """The effective, non-secret configuration of this process (defaults < config.yaml < environment)."""
    return {"agent_version": AGENT_VERSION, "changelog": CHANGELOG, "enabled_modes": list(settings.enabled_modes), "settings": settings.snapshot()}
