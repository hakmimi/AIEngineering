import json
import logging
import time

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import settings
from errors import AppError
from rag import get_rag_answer
from retrieval import get_relevant_chunks
from security import rate_limit, require_api_key

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Production RAG API")


@app.middleware("http")
async def latency_middleware(request: Request, call_next):
    """Measure full request latency (includes auth, validation, serialization)."""
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


@app.get("/health")
def get_health():
    return {"status": "ok"}


@app.get("/ready")
def get_ready():
    checks = {
        "docs_file": settings.docs_path.exists(),
        "embedded_chunks_file": settings.embedded_chunks_path.exists(),
        "openai_api_key": bool(settings.openai_api_key),
        "api_key_auth_enabled": bool(settings.app_api_key),
    }
    critical = ["docs_file", "embedded_chunks_file", "openai_api_key"]
    return {"status": "ready" if all(checks[c] for c in critical) else "degraded", "checks": checks}


@app.get("/docs-count")
def docs_count():
    with settings.docs_path.open("r", encoding="utf8") as f:
        return {"documents": len(json.load(f))}


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=settings.max_query_length)
    top_k: int = Field(default=4, ge=1, le=settings.max_top_k)


protected = [Depends(require_api_key), Depends(rate_limit)]


@app.post("/search", dependencies=protected)
def search_docs(request: SearchRequest) -> dict:
    results = get_relevant_chunks(request.query, request.top_k)
    return {"results": results}


@app.post("/rag", dependencies=protected)
def rag(request: SearchRequest) -> dict:
    return {"results": get_rag_answer(request.query, request.top_k)}
