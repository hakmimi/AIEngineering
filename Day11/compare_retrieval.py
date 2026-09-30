"""Compare Day 7 list search vs Day 8 FAISS search on the same queries.

Usage: python compare_retrieval.py            (needs OPENAI_API_KEY for the query embeddings)
Writes data/retrieval_comparison.json
"""
import json
import logging
import time

from config import settings
from embeddings import get_embedding
from retrieval import faiss_search, get_store, legacy_search

QUERIES = [
    "Why is Jerusalem important to three religions?",
    "Where can I float on salt water?",
    "Which city is the startup and tech center?",
    "Tell me about the ancient fortress on a plateau",
    "What is the desert crater in the Negev?",
    "Israeli cybersecurity industry",
    "Tell me about Lumaria",
    "What is the capital of France?",
]
TOP_K = 4
REPEATS = 200  # search itself is microseconds; repeat to get a stable timing


def timed(fn, *args) -> tuple[list[dict], float]:
    started = time.perf_counter()
    for _ in range(REPEATS):
        result = fn(*args)
    return result, (time.perf_counter() - started) * 1000 / REPEATS


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    get_store()  # load/build once so timings exclude index loading
    rows = []
    for query in QUERIES:
        vector = get_embedding(query)
        old, old_ms = timed(legacy_search, vector, query, TOP_K)
        new, new_ms = timed(faiss_search, vector, query, TOP_K)
        old_ids = [(c["doc_id"], c["chunk_id"]) for c in old]
        new_ids = [(c["doc_id"], c["chunk_id"]) for c in new]
        overlap = (len(set(old_ids) & set(new_ids)) / max(len(old_ids), len(new_ids))) if (old_ids or new_ids) else 1.0
        rows.append({"query": query, "same_top1": old_ids[:1] == new_ids[:1], "overlap": round(overlap, 2),
                     "legacy_ms": round(old_ms, 3), "faiss_ms": round(new_ms, 3),
                     "legacy_ids": old_ids, "faiss_ids": new_ids})
        print(f"{query[:48]:48} top1_same={rows[-1]['same_top1']} overlap={overlap:.2f} "
              f"legacy={old_ms:.3f}ms faiss={new_ms:.3f}ms")

    summary = {
        "chunks": get_store().index.ntotal,
        "avg_overlap": round(sum(r["overlap"] for r in rows) / len(rows), 3),
        "top1_agreement": round(sum(r["same_top1"] for r in rows) / len(rows), 3),
        "avg_legacy_ms": round(sum(r["legacy_ms"] for r in rows) / len(rows), 3),
        "avg_faiss_ms": round(sum(r["faiss_ms"] for r in rows) / len(rows), 3),
    }
    print(summary)
    out = settings.base_dir / "data" / "retrieval_comparison.json"
    out.write_text(json.dumps({"summary": summary, "queries": rows}, indent=2), encoding="utf8")


if __name__ == "__main__":
    main()
