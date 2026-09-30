"""HTTP endpoints. Business logic lives in rag.py / retrieval.py, never here."""
import json

from fastapi import APIRouter, Depends

from assistant import ask
from chat import chat
from config import settings
from graph import run_graph
from memory import memory, validate_session_id
from pipeline import run_pipeline
from rag import get_rag_answer
from retrieval import get_relevant_chunks
from schemas import ChatRequest, GraphRequest, SearchRequest
from security import rate_limit, require_api_key
from tool_agent import run_with_tools

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


@router.post("/ask/tools", dependencies=protected)
def ask_with_tools(request: SearchRequest) -> dict:
    """Day 11: Query -> decision -> tool OR LLM -> response (tool call is returned for transparency)."""
    return {"results": run_with_tools(request.query, request.top_k)}


@router.post("/chat", dependencies=protected)
def chat_endpoint(request: ChatRequest) -> dict:
    """Day 12: multi-turn RAG. The same session_id continues the conversation."""
    return {"results": chat(request.session_id, request.query, request.top_k)}


@router.get("/session/{session_id}", dependencies=protected)
def get_session(session_id: str) -> dict:
    validate_session_id(session_id)
    history = memory.get_history(session_id)
    return {"session_id": session_id, "turns": len(history) // 2, "messages": history}


@router.delete("/session/{session_id}", dependencies=protected)
def delete_session(session_id: str) -> dict:
    validate_session_id(session_id)
    return {"session_id": session_id, "deleted": memory.clear(session_id)}


@router.post("/ask", dependencies=protected)
def ask_endpoint(request: ChatRequest) -> dict:
    """Day 14: the complete assistant - memory + rule-based tools + RAG in one call."""
    return {"results": ask(request.session_id, request.query, request.top_k)}


@router.post("/rag/graph", dependencies=protected)
def rag_graph_endpoint(request: GraphRequest) -> dict:
    """Days 15-19: the LangGraph workflow. Send `session_id` to enable memory (history + user facts)."""
    if request.session_id:
        validate_session_id(request.session_id)
    return {"results": run_graph(request.query, request.top_k, request.session_id)}
