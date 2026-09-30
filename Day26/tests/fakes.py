"""Deterministic stand-ins for the network calls, so retrieval can be tested on the REAL documents offline.

HashEmbedder: tf-idf bag-of-words hashed into a fixed-size vector. It knows nothing about meaning (no synonyms),
so it only rewards shared words - which makes tests predictable: a query that names a topic's words must find it,
and a query with no shared words must find nothing.
"""
import json
import math
import re
import zlib
from collections import Counter
from pathlib import Path

from chunk import chunk_text

ROOT = Path(__file__).resolve().parent.parent
DIM = 32768        # large on purpose: few hash collisions, so unrelated words really score ~0
_WORD = re.compile(r"[a-z0-9]+")


class HashEmbedder:
    def __init__(self, corpus: list[str]):
        docs = [set(_WORD.findall(t.lower())) for t in corpus]
        df = Counter(w for d in docs for w in d)
        self.idf = {w: math.log((1 + len(docs)) / (1 + n)) + 1 for w, n in df.items()}
        self.default_idf = math.log(1 + len(docs)) + 1     # unseen word = rarest possible

    def __call__(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        for word, count in Counter(_WORD.findall(text.lower())).items():
            vec[zlib.crc32(word.encode()) % DIM] += count * self.idf.get(word, self.default_idf)
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def load_real_chunks() -> list[dict]:
    """Chunk the real docs exactly like embedding_pipeline does, WITHOUT embeddings."""
    docs = json.loads((ROOT / "data" / "docs.json").read_text(encoding="utf8"))
    categories = json.loads((ROOT / "data" / "categories.json").read_text(encoding="utf8"))
    chunks = []
    for doc in docs:
        for chunk_id, text in enumerate(chunk_text(doc["text"])):
            chunks.append({"doc_id": doc["id"], "chunk_id": chunk_id, "topic": doc["topic"],
                           "category": categories.get(doc["topic"], "other"), "text": text})
    return chunks


def build_fake_index():
    """(embedder, VectorStore) over the real chunks, embedded as '<topic>: <text>' like the real pipeline."""
    from vector_store import VectorStore
    chunks = load_real_chunks()
    embedder = HashEmbedder([f"{c['topic']}: {c['text']}" for c in chunks])
    for c in chunks:
        c["embedded_text"] = embedder(f"{c['topic']}: {c['text']}")
    return embedder, VectorStore.build(chunks)
