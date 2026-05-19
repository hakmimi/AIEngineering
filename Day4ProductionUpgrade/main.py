from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
import json
from retrieval import get_relevant_chunks
from pydantic import BaseModel , Field
import logging
from rag import get_rag_answer
from config import settings
from errors import AppError
from security import rate_limit, require_api_key

logging.basicConfig(level=logging.INFO,
                       format= "%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Production RAG API")


@app.exception_handler(AppError)
def app_error_handler(request: Request, exc: AppError):
    logger.warning("Application error on %s: %s", request.url.path, exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message},
    )


@app.exception_handler(Exception)
def unexpected_error_handler(request: Request, exc: Exception):
    logger.exception("Unexpected error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.get('/health')
def get_health():
    return({'Status':'Ok'})


@app.get('/ready')
def get_ready():
    checks = {
        "docs_file": settings.docs_path.exists(),
        "embedded_chunks_file": settings.embedded_chunks_path.exists(),
        "openai_api_key": bool(settings.openai_api_key),
        "api_key_auth_enabled": bool(settings.app_api_key),
    }
    critical_checks = ["docs_file", "embedded_chunks_file", "openai_api_key"]
    status = "ready" if all(checks[name] for name in critical_checks) else "degraded"
    return {"status": status, "checks": checks}


@app.get('/docs-count')
def docs_count():
    with settings.docs_path.open('r',encoding='utf8') as f:
        docs = json.load(f)
    
    return {
        'documents' : len(docs)
    }

class SearchRequest(BaseModel):
    # Original request accepted unbounded query/top_k values.
    query : str = Field(..., min_length=1, max_length=settings.max_query_length)
    top_k : int = Field(default=4, ge=1, le=settings.max_top_k)

protected_endpoint = [Depends(require_api_key), Depends(rate_limit)]


@app.post('/search', dependencies=protected_endpoint)
def search_docs(request : SearchRequest) -> dict :
    logging.info("Search query received: length=%s", len(request.query))
    
    response = get_relevant_chunks(request.query,request.top_k)
    logging.info(f"Top K: {request.top_k}")
    logging.info(f"Retrieved chunks: {len(response)}")
    
    return({'results':response})

@app.post('/rag', dependencies=protected_endpoint)
def get_rag_llm(request : SearchRequest) -> dict:
    logging.info("RAG query received: length=%s", len(request.query))
    response = get_rag_answer(request.query,request.top_k)
    logging.info(f"Top K: {request.top_k}")
    logging.info(f"Retrieved chunks: {len(response.get('retrieved_chunks', []))}")
    
    return({'results':response})
    

