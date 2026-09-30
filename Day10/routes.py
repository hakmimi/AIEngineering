"""HTTP endpoints. Business logic lives in rag.py / retrieval.py, never here."""
import json

from fastapi import APIRouter, Depends

from config import settings
from pipeline import run_pipeline
from rag import get_rag_answer
from retrieval import get_relevant_chunks
from schemas import SearchRequest
from security import rate_limit, require_api_key

router = APIRouter()
protected = [Depends(require_api_key), Depends(rate_limit)]


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/ready")
def ready():
    checks = {
        "docs_file": settings.docs_path.exists(),
        "embedded_chunks_file": settings.embedded_chunks_path.exists(),
        "openai_api_key": bool(settings.openai_api_key),
        "api_key_auth_enabled": bool(settings.app_api_key),
    }
    critical = ["docs_file", "embedded_chunks_file", "openai_api_key"]
    return {"status": "ready" if all(checks[c] for c in critical) else "degraded", "checks": checks}


@router.get("/docs-count")
def docs_count():
    with settings.docs_path.open("r", encoding="utf8") as f:
        return {"documents": len(json.load(f))}


@router.post("/search", dependencies=protected)
def search(request: SearchRequest) -> dict:
    return {"results": get_relevant_chunks(request.query, request.top_k, request.filters())}


@router.post("/rag", dependencies=protected)
def rag(request: SearchRequest) -> dict:
    return {"results": get_rag_answer(request.query, request.top_k, request.filters())}


@router.post("/rag/multistep", dependencies=protected)
def rag_multistep(request: SearchRequest) -> dict:
    """Day 10: analyze -> retrieve -> extract -> compose. Response includes the intermediate trace."""
    return {"results": run_pipeline(request.query, request.top_k, request.filters())}
