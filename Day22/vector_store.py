"""FAISS-backed vector store with on-disk persistence.

Vectors are L2-normalised and stored in an inner-product index, so the inner product IS the cosine
similarity (same scale as the Day 3-7 pure-Python `cosine_similarity`).
"""
import json
import logging
import time
from pathlib import Path

import faiss
import numpy as np

from config import settings
from errors import DataStoreError

logger = logging.getLogger(__name__)


def _normalise(matrix: np.ndarray) -> np.ndarray:
    matrix = np.ascontiguousarray(matrix, dtype="float32")
    faiss.normalize_L2(matrix)  # in place
    return matrix


class VectorStore:
    def __init__(self, index: faiss.Index, metadata: list[dict]):
        self.index = index
        self.metadata = metadata  # metadata[i] describes vector i

    # -- building / persistence -------------------------------------------------
    @classmethod
    def build(cls, chunks: list[dict]) -> "VectorStore":
        if not chunks:
            raise DataStoreError("Cannot build a vector index from zero chunks")
        vectors = _normalise(np.array([c["embedded_text"] for c in chunks]))
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        metadata = [{k: v for k, v in c.items() if k != "embedded_text"} for c in chunks]
        logger.info("faiss_index_built vectors=%s dim=%s", index.ntotal, vectors.shape[1])
        return cls(index, metadata)

    def save(self, index_path: Path, meta_path: Path) -> None:
        faiss.write_index(self.index, str(index_path))
        meta_path.write_text(json.dumps(self.metadata, ensure_ascii=False), encoding="utf8")
        logger.info("faiss_index_saved path=%s", index_path)

    @classmethod
    def load(cls, index_path: Path, meta_path: Path) -> "VectorStore":
        try:
            index = faiss.read_index(str(index_path))
            metadata = json.loads(meta_path.read_text(encoding="utf8"))
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            raise DataStoreError("FAISS index files are missing or corrupt") from exc
        if index.ntotal != len(metadata):
            raise DataStoreError("FAISS index and metadata are out of sync")
        return cls(index, metadata)

    # -- querying -----------------------------------------------------------------
    def search(self, query_vector: list[float], k: int) -> list[dict]:
        """Return up to k chunks (best first), each with a cosine `similarity`."""
        k = max(1, min(k, self.index.ntotal))
        query = _normalise(np.array([query_vector]))
        scores, ids = self.index.search(query, k)
        return [{**self.metadata[i], "similarity": float(s)}
                for s, i in zip(scores[0], ids[0]) if i != -1]


def _is_stale(index_path: Path, source_path: Path) -> bool:
    return not index_path.exists() or index_path.stat().st_mtime < source_path.stat().st_mtime


def load_or_build_store() -> VectorStore:
    """Load the persisted index; rebuild from embedded_chunks.json when missing or older than it."""
    index_path, meta_path = settings.faiss_index_path, settings.faiss_meta_path
    source = settings.embedded_chunks_path
    if not source.exists() and not index_path.exists():
        raise DataStoreError("Neither a FAISS index nor embedded chunks exist - run embedding_pipeline.py")

    if source.exists() and _is_stale(index_path, source):
        started = time.perf_counter()
        chunks = json.loads(source.read_text(encoding="utf8"))
        store = VectorStore.build(chunks)
        store.save(index_path, meta_path)
        logger.info("faiss_rebuilt took_ms=%.1f", (time.perf_counter() - started) * 1000)
        return store
    return VectorStore.load(index_path, meta_path)
