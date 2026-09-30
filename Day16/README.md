# Day 16 – Conditional Routing in the Graph

## Goal

Make the workflow **choose different paths** – replace scattered `if/else` with an explicit router node and conditional edges, and answer the design question *"should routing be rule-based or LLM-based?"* with data.

```text
Query → Router node ─┬─ direct   → canned answer                  (0 API calls)
                     ├─ fallback → "please rephrase"              (0 API calls)
                     └─ rag ──── simple  → retrieve (top_k ≤ 3)  → LLM
                               └ complex → retrieve (top_k ≥ 6, wide margin) → LLM
```

## What changed (vs Day 15)

| File | Change |
|---|---|
| `intent.py` (new) | `Decision(route, query_type, reason, by, answer)`; `rule_classify`, `llm_classify` (fails safe to rules), `classify` (mode from `LLM_ROUTING`) |
| `graph.py` | New nodes `route_query`, `direct_answer`, `fallback_response`; conditional edges after `receive_query` and `route_query`; state gains `route`, `query_type`, `route_reason`, `routed_by` |
| `prompts.py` | `INTENT_PROMPT` (route + complexity classification) |
| `router.py` | Rule refinement: `how`/`why` are no longer "complex" markers |
| `config.py` | `LLM_ROUTING` (default off) |
| `scripts/routing_eval.py` (new) | 22 labelled messages, rules vs LLM |
| `docs/graph.md` | diagram + route table |
| `tests/test_graph.py` | 9 new tests – direct/fallback/simple/complex paths, LLM mode, LLM failure (158 pass) |

## How it was implemented

1. **Routes** – `direct` (small talk), `rag` (any information request) and `fallback` (unintelligible/too vague). Whether the *topic* is covered is deliberately **not** the router's job – retrieval and the score gate decide that.
2. **Router node vs conditional edge** – the node *decides* and writes `route`, `query_type`, `route_reason`, `routed_by` into state; `_after_route` only *reads* state and returns the next node name. Decisions are therefore logged (`graph_route route=… type=… reason=… by=…`), returned in the API response, and testable without running the graph.
3. **Simple vs complex** – "simple" = one fact/topic → small context; "complex" = comparison/several entities → `top_k ≥ 6` and the wide score margin from Day 13.
4. **Optional LLM classification** – same `Decision` type, structured JSON output; on any failure it falls back to the rules.
5. **State enrichment** – the query type and the reason stay in state so later nodes (and Day 23's logs) can use them.

## Rule-based vs LLM-based routing (22 labelled messages, measured live)

| Router | Route accuracy | Complexity accuracy (rag cases) | Cost / latency |
|---|---:|---:|---|
| Rules (before refinement) | 100 % | 78.6 % – `how`/`why` questions wrongly "complex" | free, < 1 ms |
| Rules (after refinement) | **100 %** | **92.9 %** (misses "Why is Jerusalem holy to three religions?") | free, < 1 ms |
| LLM | 95.5 % (sent bare "Jerusalem" to rag – arguably fine) | 100 % | one extra LLM call per request (~1 s) |

Conclusion: **rules by default** (deterministic, free, explainable, already 100 % on the routing decision), LLM classification as an opt-in (`LLM_ROUTING=1`) when nuance in complexity matters more than latency/cost. A hybrid (rules first, LLM only when unsure) is the natural next step.

## Live test

| Message | Route | Type | Source | Time |
|---|---|---|---|---|
| hello | direct | – | direct | ~0 ms |
| ok | fallback | – | fallback | ~0 ms |
| Where is Masada? | rag | simple | rag | ~2–3 s |
| Compare Tel Aviv and Haifa | rag | complex | rag | ~3 s |
| What is the capital of France? | rag | simple | no_context (score gate) | ~0.3 s |

## Run & test

```bash
cd Day16
python -m pytest tests -q
python -m scripts.routing_eval          # ~22 short LLM calls
LLM_ROUTING=1 uvicorn main:app          # optional LLM router
# POST /rag/graph {"query": "Compare Tel Aviv and Haifa"}
```
