import json
import logging
import re
import time
from functools import lru_cache

from config import settings
from embeddings import get_embedding
from errors import DataStoreError
from similarity import cosine_similarity

logger = logging.getLogger(__name__)

_STOPWORDS = {"the", "a", "an", "is", "are", "of", "in", "on", "and", "to", "why", "what",
              "how", "who", "does", "do", "it", "its", "for", "with", "about", "tell", "me"}


@lru_cache(maxsize=1)
def load_embedded_chunks() -> list[dict]:
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


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def keyword_overlap(query: str, text: str) -> float:
    """Fraction of query keywords that appear in the chunk (0..1)."""
    q = _keywords(query)
    return len(q & _keywords(text)) / len(q) if q else 0.0


def score_chunk(query: str, chunk_text: str, similarity: float) -> float:
    """Final rank score = cosine similarity + small lexical boost."""
    return similarity + settings.keyword_boost * keyword_overlap(query, chunk_text)


def filter_chunks(chunks: list[dict]) -> list[dict]:
    """Drop chunks below the minimum score (irrelevant context is worse than none)."""
    return [c for c in chunks if c["score"] >= settings.min_chunk_score]


def get_relevant_chunks(query: str, top_k: int = 4) -> list[dict]:
    started_at = time.time()
    top_k = max(1, min(top_k, settings.max_top_k))
    query_embedding = get_embedding(query)
    results = []

    for chunk in load_embedded_chunks():
        try:
            similarity = cosine_similarity(query_embedding, chunk["embedded_text"])
            results.append({
                "doc_id": chunk["doc_id"],
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
                "similarity": similarity,
                "score": score_chunk(query, chunk["text"], similarity),
            })
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping invalid embedded chunk: %s", exc)

    results.sort(key=lambda x: x["score"], reverse=True)
    kept = filter_chunks(results[:top_k])
    logger.info("retrieval query_len=%s candidates=%s kept=%s best=%.3f took=%.2fs",
                len(query), len(results), len(kept),
                kept[0]["score"] if kept else 0.0, time.time() - started_at)
    return kept
