"""App wiring only: logging, request-id + latency middleware, error handlers, routes."""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from errors import AppError
from observability import configure_logging, log_event, new_request_id, request_id_var
from routes import router

configure_logging()
logger = logging.getLogger("http")

app = FastAPI(title="Production RAG API")
app.include_router(router)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Give every request an id, log start/end with latency, and echo the id + latency in response headers."""
    request_id = request.headers.get("x-request-id") or new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    log_event(logger, "request_start", method=request.method, path=request.url.path)
    try:
        response = await call_next(request)
    except Exception:
        log_event(logger, "request_crashed", level=logging.ERROR, method=request.method, path=request.url.path)
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    log_event(logger, "request_end", method=request.method, path=request.url.path,
              status=response.status_code, latency_ms=elapsed_ms)
    request_id_var.reset(token)
    return response


@app.exception_handler(AppError)
def app_error_handler(request: Request, exc: AppError):
    log_event(logger, "app_error", level=logging.WARNING, path=request.url.path, status=exc.status_code, msg=exc.message)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "request_id": request_id_var.get()})


@app.exception_handler(Exception)
def unexpected_error_handler(request: Request, exc: Exception):
    logger.error("unexpected_error path=%s", request.url.path, exc_info=exc)   # exc_info=exc: no active except block here
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "request_id": request_id_var.get()})
