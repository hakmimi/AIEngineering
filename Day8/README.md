# Day 8 – FAISS / Vector DB

## Goal

Replace the in-memory Python list search with a real vector index that is **persisted on disk** and reusable.

```text
Query → embed → FAISS index → keyword re-rank → filter → LLM
```

## What changed (vs Day 7)

| File | Change |
|---|---|
| `vector_store.py` (new) | `VectorStore`: build / save / load / search over a `faiss.IndexFlatIP`; `load_or_build_store()` rebuilds when the index is missing or older than `embedded_chunks.json` |
| `retrieval.py` | `faiss_search()` is now the production path; the old list scan is kept as `legacy_search()` for comparison; logs `embed_ms` and `search_ms` separately |
| `compare_retrieval.py` (new) | Runs both backends on 8 queries, reports top-1 agreement, overlap and timing → `data/retrieval_comparison.json` |
| `config.py` | `faiss_index_path`, `faiss_meta_path`, `FAISS_CANDIDATE_MULTIPLIER` |
| `data/faiss.index`, `data/faiss_meta.json` (generated) | Persisted index + chunk metadata (vectors are not duplicated in the JSON) |
| `tests/test_vector_store.py` (new) | 7 offline tests: ordering equals pure-Python cosine, k clamping, save/load round-trip, corrupt/out-of-sync files, empty build |

## How it was implemented

1. **Install** `faiss-cpu` (+ `numpy`).
2. **Index** – vectors are L2-normalised and put in an inner-product index, so the score *is* cosine similarity and the Day 5 thresholds (`0.55`, `0.30`) stay valid.
3. **Store embeddings / persist** – `faiss.write_index` + a metadata JSON where row *i* describes vector *i*. `load` checks `ntotal == len(metadata)` to catch drift.
4. **Query** – FAISS returns `top_k × 3` candidates; the same keyword boost and score filter as Day 5 re-rank them, so behaviour is identical and only the nearest-neighbour step changed.
5. **Compare** – `compare_retrieval.py` embeds each query once and times both searches over 200 repetitions.

## Results (77 chunks, 8 queries, measured live)

| Metric | Result |
|---|---|
| Top-1 agreement old vs new | 100 % |
| Average top-k overlap | 1.00 |
| Search time – list scan | ≈ 19.6 ms |
| Search time – FAISS | ≈ 0.29 ms (≈ 65× faster) |

Why vector DB / why not list search: a Python loop is O(n) with a large constant; FAISS does the same math in optimised C/SIMD, and the index survives restarts. Note the *whole* retrieval step still takes ~1.4 s in a real request because the **query embedding API call** dominates – the next lever is caching (later days).

## Run & test

```bash
cd Day8
pip install -r requirements.txt
python embedding_pipeline.py     # only if data/embedded_chunks.json is missing
python compare_retrieval.py
python -m pytest tests -q        # 41 tests
```

## Caveats

`IndexFlatIP` is exact (brute force) and is right for 77 vectors; approximate indexes (IVF/HNSW) only pay off at ~100k+ vectors.
