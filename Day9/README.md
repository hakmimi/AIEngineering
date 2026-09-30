# Day 9 – Retrieval Quality

## Goal

"Retrieval quality = answer quality." Improve *what* reaches the LLM: better ranking, metadata filtering, adaptive top-k and clearer context formatting – and **measure** it instead of eyeballing.

## What changed (vs Day 8)

| Area | Change |
|---|---|
| Chunk metadata | Each chunk now carries `topic` and `category` (`data/categories.json`: city, nature, history, culture, technology, society, industry) |
| Embedding input | Chunks are embedded as `"<topic>: <text>"` (contextual embedding), while the stored text is unchanged |
| Ranking (`retrieval.py`) | score = cosine + keyword-overlap boost + **topic boost** when the topic is named in the query |
| Adaptive top-k | `relative_cutoff()` keeps only chunks within `RELATIVE_SCORE_MARGIN` (0.12) of the best score, so a clear single answer isn't padded with noise |
| Filtering | `get_relevant_chunks(query, top_k, filters)`; API accepts optional `category` / `topic` |
| Context format (`rag.py`) | `[doc:chunk|topic] text`, best chunk first |
| Measurement (new) | `retrieval_quality.py`: 20 labelled queries → hit@1, hit@3, MRR, precision, average chunks; `compare` command |
| Tests | `tests/test_retrieval_quality.py` (8 tests); older tests adapted to the new `filters` argument (49 pass) |

## How it was implemented

1. **Metadata** – `embedding_pipeline.py` joins each doc's topic with the category map and writes both into every chunk; `VectorStore` keeps them in the metadata file.
2. **Filtering** – FAISS has no native filter, so with a filter the whole (77-vector) index is fetched and filtered in Python (`matches_filters`, case-insensitive, all fields must match). At larger scale you would use a partitioned or filtered index.
3. **Ranking** – `score_chunk` adds `TOPIC_BOOST` (0.15) when the chunk's topic string appears in the query. Simple, explainable, tunable.
4. **Top-k** – requested `top_k` stays an upper bound; the relative cutoff decides how many are actually useful.
5. **Experiment protocol** – baseline was recorded *before* changing anything (`quality_baseline.json`), then re-recorded after (`quality_improved.json`).

## Results (20 queries, measured live)

| Metric | Baseline (Day 8 logic) | Improved | Δ |
|---|---:|---:|---:|
| hit@1 | 1.000 | 0.950 | −0.05 |
| MRR | 1.000 | 0.950 | −0.05 |
| **precision** (share of returned chunks on-topic) | 0.433 | **0.912** | **+0.48** |
| avg chunks sent to LLM | 3.70 | 1.60 | −2.1 (≈ 57 % less context) |

The single miss is a deliberately vague query with a strict metadata filter ("Something about technology in the south" + `category=city`): best similarity is ~0.20, below `MIN_CHUNK_SCORE`, so the system returns nothing rather than weak context – a safe refusal, but a real trade-off of strict filters. The old baseline could not apply the filter at all.

### Threshold recalibration (found by live testing)

After topic-prefixed embeddings the LLM gate (`RETRIEVAL_THRESHOLD=0.55`, tuned on Day 5) wrongly refused *"Where can I go skiing?"* (best score 0.45, correct topic Mount Hermon). Measured best scores: relevant queries 0.45–0.97, out-of-domain ("capital of France") ≤ 0.31, so the default is now **0.40** – it sits in the gap.

## Run & test

```bash
cd Day9
python embedding_pipeline.py      # rebuilds embeddings with metadata (needs OPENAI_API_KEY)
python retrieval_quality.py improved
python retrieval_quality.py compare baseline improved
python -m pytest tests -q
```

## Caveats

- The dataset is small and mostly easy; hit@1 was already saturated, so **precision** is the metric that shows the gain.
- Category labels were assigned by hand; in a real system they come from the data source.
