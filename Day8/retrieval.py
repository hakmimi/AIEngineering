import json
import logging
import re
import time
from functools import lru_cache

from config import settings
from embeddings import get_embedding
from errors import DataStoreError
from similarity import cosine_similarity
from vector_store import VectorStore, load_or_build_store

logger = logging.getLogger(__name__)

_STOPWORDS = {"the", "a", "an", "is", "are", "of", "in", "on", "and", "to", "why", "what",
              "how", "who", "does", "do", "it", "its", "for", "with", "about", "tell", "me"}


# --- data access ---------------------------------------------------------------
@lru_cache(maxsize=1)
def load_embedded_chunks() -> list[dict]:
    """Raw chunks with vectors (only used by the legacy list search and the index build)."""
    try:
        with settings.embedded_chunks_path.open("r", encoding="utf8") as f:
            chunks = json.load(f)
    except FileNotFoundError as exc:
        raise DataStoreError("Embedded chunks file was not found") from exc
    except json.JSONDecodeError as exc:
        raise DataStoreError("Embedded chunks file contains invalid JSON") from exc
    if not isinstance(chunks, list):
        raise DataStoreError("Embedded chunks file must contain a list")
    return chunks


@lru_cache(maxsize=1)
def get_store() -> VectorStore:
    return load_or_build_store()


# --- scoring -------------------------------------------------------------------
def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def keyword_overlap(query: str, text: str) -> float:
    q = _keywords(query)
    return len(q & _keywords(text)) / len(q) if q else 0.0


def score_chunk(query: str, chunk_text: str, similarity: float) -> float:
    return similarity + settings.keyword_boost * keyword_overlap(query, chunk_text)


def filter_chunks(chunks: list[dict]) -> list[dict]:
    return [c for c in chunks if c["score"] >= settings.min_chunk_score]


def _rank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    for c in candidates:
        c["score"] = score_chunk(query, c["text"], c["similarity"])
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return filter_chunks(candidates[:top_k])


def _public(chunk: dict) -> dict:
    return {k: chunk[k] for k in ("doc_id", "chunk_id", "text", "similarity", "score")}


# --- retrieval -----------------------------------------------------------------
def legacy_search(query_embedding: list[float], query: str, top_k: int) -> list[dict]:
    """Day 3-7 approach: cosine against every chunk in a Python list (O(n) per query). Kept for comparison."""
    results = []
    for chunk in load_embedded_chunks():
        try:
            sim = cosine_similarity(query_embedding, chunk["embedded_text"])
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping invalid embedded chunk: %s", exc)
            continue
        results.append({"doc_id": chunk["doc_id"], "chunk_id": chunk["chunk_id"],
                        "text": chunk["text"], "similarity": sim})
    results.sort(key=lambda c: c["similarity"], reverse=True)
    return _rank(query, results[:top_k * settings.faiss_candidate_multiplier], top_k)


def faiss_search(query_embedding: list[float], query: str, top_k: int) -> list[dict]:
    """Day 8 approach: FAISS nearest-neighbour search, then the same keyword re-rank."""
    candidates = get_store().search(query_embedding, top_k * settings.faiss_candidate_multiplier)
    return _rank(query, candidates, top_k)


def get_relevant_chunks(query: str, top_k: int = 4) -> list[dict]:
    started_at = time.perf_counter()
    top_k = max(1, min(top_k, settings.max_top_k))
    query_embedding = get_embedding(query)
    embed_ms = (time.perf_counter() - started_at) * 1000

    search_started = time.perf_counter()
    kept = [_public(c) for c in faiss_search(query_embedding, query, top_k)]
    search_ms = (time.perf_counter() - search_started) * 1000

    logger.info("retrieval backend=faiss query_len=%s kept=%s best=%.3f embed_ms=%.1f search_ms=%.2f",
                len(query), len(kept), kept[0]["score"] if kept else 0.0, embed_ms, search_ms)
    return kept
