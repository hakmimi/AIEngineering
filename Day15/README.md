# Day 15 – LangGraph Basics

## Goal

Understand *why* frameworks like LangGraph exist by rebuilding the manual pipeline as a **graph-based, stateful workflow**, while keeping FastAPI as the outside entry point.

```text
Client → FastAPI (/rag/graph) → LangGraph: receive_query → retrieve_context → call_llm → Response
```

## What changed (vs Day 14)

| File | Change |
|---|---|
| `graph.py` (new) | `RagState` (shared state), three node functions, `build_graph()` with a conditional edge, `run_graph()` |
| `routes.py` | `POST /rag/graph` – FastAPI calls the compiled graph; `/rag`, `/ask`, `/chat` are unchanged |
| `docs/graph.md`, `docs/graph.mmd` (new) | diagram + node table (Mermaid generated from the compiled graph) |
| `tests/test_graph.py` (new) | 8 offline tests (150 pass) |
| dependency | `langgraph` |

## How it was implemented

1. **Concepts** – *state* = the dict every node reads/writes; *node* = a function `state → partial update`; *edge* = the order between nodes; *conditional edge* = a function that picks the next node from the state.
2. **What should be a node?** A step with a clear input/output and its own failure mode: normalising the query (no I/O), retrieval (embedding + index), the LLM call (network). Pure helpers such as `build_context` stay ordinary functions used *inside* nodes.
3. **State object** – a `TypedDict` (`question`, `top_k`, `chunks`, `answer`, `confidence`, `source`, `trace`, `timings`). Two keys use **reducers**: `trace` appends and `timings` merges, so each node adds information without clobbering the previous one.
4. **Nodes** – reuse the tested modules (`get_relevant_chunks`, `validate_context`, `get_answer`, prompts); a `@timed` decorator logs per-node latency and appends to `trace`.
5. **The LLM is one node, not the system** – it only does work when retrieval returned usable context; provider errors become a fallback answer inside the node, so the graph always ends cleanly.
6. **Orchestration lives in the graph, not in FastAPI** – the endpoint only validates the request and calls `run_graph()`; the response has the same fields as `/rag` plus `graph.trace`.
7. **Conditional edge** – a blank question ends the run right after `receive_query` (no API calls). Real branching arrives on Day 16.

## Live test (3 queries)

| Query | Trace | Result |
|---|---|---|
| Where is Masada? | receive_query → retrieve_context → call_llm | grounded answer, 2.7 s (retrieval 1.5 s, LLM 1.2 s) |
| What is the capital of France? | all three nodes; `call_llm` does no LLM work | `no_context` refusal, 0.19 s |
| (blank) | receive_query only | `invalid_input` |

## Why a graph instead of simple functions?

The functions version hard-codes the order inside one body. The graph version makes the order *data* that can be inspected (`draw_mermaid`), timed per node, extended with branches/retries/persistence, and resumed – exactly what Days 16–19 add.

## Run & test

```bash
cd Day15
pip install -r requirements.txt      # includes langgraph
python -m pytest tests -q
# POST /rag/graph {"query": "Where is Masada?"}
```
