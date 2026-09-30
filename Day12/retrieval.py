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


def topic_in_query(query: str, topic: str | None) -> bool:
    return bool(topic) and topic.lower() in query.lower()


def score_chunk(query: str, chunk_text: str, similarity: float, topic: str | None = None) -> float:
    """similarity + keyword-overlap boost + boost when the chunk's topic is named in the query."""
    score = similarity + settings.keyword_boost * keyword_overlap(query, chunk_text)
    return score + (settings.topic_boost if topic_in_query(query, topic) else 0.0)


def filter_chunks(chunks: list[dict]) -> list[dict]:
    return [c for c in chunks if c["score"] >= settings.min_chunk_score]


def relative_cutoff(chunks: list[dict]) -> list[dict]:
    """Adaptive top-k: keep only chunks close to the best one (drops the noisy tail)."""
    if not chunks:
        return chunks
    floor = chunks[0]["score"] - settings.relative_score_margin
    return [c for c in chunks if c["score"] >= floor]


def matches_filters(chunk: dict, filters: dict | None) -> bool:
    """Metadata filter: every given field must equal the chunk's value (case-insensitive)."""
    return all(str(chunk.get(k, "")).lower() == str(v).lower() for k, v in (filters or {}).items() if v)


def _rank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    for c in candidates:
        c["score"] = score_chunk(query, c["text"], c["similarity"], c.get("topic"))
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return relative_cutoff(filter_chunks(candidates[:top_k]))


def _public(chunk: dict) -> dict:
    keys = ("doc_id", "chunk_id", "topic", "category", "text", "similarity", "score")
    return {k: chunk.get(k) for k in keys}


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


def faiss_search(query_embedding: list[float], query: str, top_k: int, filters: dict | None = None) -> list[dict]:
    """FAISS search + metadata filter + re-rank. FAISS has no native filter, so with a filter we
    over-fetch the whole (small) index and filter afterwards; at scale use a filtered/partitioned index."""
    store = get_store()
    fetch = store.index.ntotal if filters else top_k * settings.faiss_candidate_multiplier
    candidates = [c for c in store.search(query_embedding, fetch) if matches_filters(c, filters)]
    return _rank(query, candidates, top_k)


def get_relevant_chunks(query: str, top_k: int = 4, filters: dict | None = None) -> list[dict]:
    started_at = time.perf_counter()
    top_k = max(1, min(top_k, settings.max_top_k))
    query_embedding = get_embedding(query)
    embed_ms = (time.perf_counter() - started_at) * 1000

    search_started = time.perf_counter()
    kept = [_public(c) for c in faiss_search(query_embedding, query, top_k, filters)]
    search_ms = (time.perf_counter() - search_started) * 1000

    logger.info("retrieval backend=faiss filters=%s query_len=%s kept=%s best=%.3f embed_ms=%.1f search_ms=%.2f",
                filters or {}, len(query), len(kept), kept[0]["score"] if kept else 0.0, embed_ms, search_ms)
    return kept
