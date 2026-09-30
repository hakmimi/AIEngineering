"""App wiring only: logging, middleware, error handlers, routes."""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from errors import AppError
from routes import router

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Production RAG API")
app.include_router(router)


@app.middleware("http")
async def latency_middleware(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    logger.info("http method=%s path=%s status=%s latency_ms=%.1f",
                request.method, request.url.path, response.status_code, elapsed_ms)
    return response


@app.exception_handler(AppError)
def app_error_handler(request: Request, exc: AppError):
    logger.warning("app_error path=%s status=%s msg=%s", request.url.path, exc.status_code, exc.message)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
def unexpected_error_handler(request: Request, exc: Exception):
    logger.exception("unexpected_error path=%s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
