# Day 10 – Multi-Step Pipelines

## Goal

Go beyond "retrieve → answer": break the problem into sequential steps, each with its own prompt and its own logged output – agent-like thinking, **without a framework**.

```text
Query → Router → analyze (LLM) → retrieve → extract facts (LLM) → compose answer (LLM) → Response
                       └─ each step logged + returned in `pipeline.trace`
```

## What changed (vs Day 9)

| File | Change |
|---|---|
| `pipeline.py` (new) | `PipelineState` dataclass + four step functions (`analyze`, `retrieve`, `extract`, `compose`) + `run_pipeline()` |
| `prompts.py` | Three specialised prompts (`ANALYZE_PROMPT`, `EXTRACT_PROMPT`, `COMPOSE_PROMPT`) and render helpers |
| `llm.py` | New generic `get_structured(prompt, schema, name)`; `get_answer` reuses the same call path |
| `rag.py` | `build_response(..., extra=...)` so the pipeline can attach its trace |
| `routes.py` | `POST /rag/multistep` (the single-step `/rag` is unchanged) |
| `run_pipeline_demo.py` (new) | Runs both pipelines on 7 query types and saves `data/pipeline_runs_v1.json` / `_v2.json` |
| `tests/test_pipeline.py` (new) | 10 offline tests (59 pass in total) |

## How it was implemented

1. **Steps** – (1) *analyze*: LLM rewrites the question into a keyword query and classifies intent (`lookup`/`comparison`/`open`); (2) *retrieve*: Day 9 retrieval on the rewritten query, wider `top_k` for comparisons, one retry with the raw question if the rewrite finds nothing; (3) *extract*: LLM copies only the relevant sentences with their tags; (4) *compose*: LLM writes the answer from those facts only.
2. **Why not one prompt?** Each prompt has one job and one JSON schema, so each step can be tested, logged and fixed alone. Small prompts are also easier to keep grounded.
3. **State + abstraction** – every step is `fn(state) -> None`; a step stops the run by setting `state.done` (safe refusal). `STEPS = [...]` is the only place that defines the flow.
4. **Failure handling** – `analyze` degrades to the raw question; any later LLM error returns the fallback answer. The rule router still short-circuits greetings with zero API calls.
5. **Intermediate outputs** – `state.record()` logs `pipeline_step step=… output=…` and stores the same data in the response (`pipeline.trace`, `search_query`, `facts`).

## Testing and refinement (live, 7 query types)

| Finding | Fix |
|---|---|
| v1 *extract* was too selective: "Which markets have spices and street food?" kept 1 fact (single-step RAG named 2 markets) | Rewrote `EXTRACT_PROMPT`: "go through EVERY passage… when in doubt, keep" → 2 facts, answer now covers both |
| Out-of-domain question ("capital of France") wasted no LLM calls after analyze | Blocked at the retrieval gate, as designed |

Latency (typical, live): single-step RAG ≈ 1.4–2.7 s, multi-step ≈ 3.7–5.5 s (3 LLM calls). **Trade-off:** multi-step is ~2–3× slower and costlier for the *same* answers on simple questions; it pays off for comparisons/multi-part questions and gives a full audit trail. That is why Day 6's router exists and why later days route between paths.

## Run & test

```bash
cd Day10
python run_pipeline_demo.py pipeline_runs_v3.json
python -m pytest tests -q
# API: POST /rag/multistep {"query": "Compare Tel Aviv and Haifa"}
```
