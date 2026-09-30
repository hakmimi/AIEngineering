# Architecture – graph-based Israel knowledge assistant (end of Week 3)

## What it is

A FastAPI service whose brain is a **LangGraph workflow**: cheap deterministic routing first, tools for exact operations, retrieval-augmented generation (FAISS) for knowledge questions, per-session memory (SQLite), uniform failure handling, and a judged evaluation harness. Diagram: `docs/graph.md` (generated from the compiled graph).

## Request flow

```text
Client ── POST /rag/graph {query, session_id?} ── auth + rate limit + validation (FastAPI)
   │
   ▼  LangGraph
 receive_query ─ blank → END
   │ session_id?  ─ yes → load_memory → contextualize (rewrite follow-up, LLM only when needed)
   ▼
 route_query  (rules by default | LLM optional)  ── writes route, query_type, reason, routed_by
   ├─ direct   → direct_answer                          0 API calls
   ├─ fallback → fallback_response                      0 API calls
   ├─ tool     → select_tool → run_tool → tool_answer   ≤ 1 LLM call (0 for rule-selected tools' selection)
   └─ rag      → retrieve_context → call_llm            1 embedding + 1 LLM call
   any node error (after retries) → fallback_node (honest message + best evidence)
   ▼
 finish → save_memory (turn + durable facts; never error text) → END
```

## Node responsibilities

| Node | Reads | Writes | Failure behaviour |
|---|---|---|---|
| `receive_query` | question | normalised question / `invalid_input` | no I/O |
| `load_memory` | store | history, user_facts | continue without memory |
| `contextualize` | history, question | standalone_question | keeps original question |
| `route_query` | question | route, query_type, reason | LLM router falls back to rules |
| `select_tool` / `run_tool` / `tool_answer` | question / tool args / result | tool_*, answer | `execute_tool` never raises; bug → fallback; LLM down → raw result |
| `retrieve_context` | question, query_type | chunks | transient errors retried, then fallback |
| `call_llm` | chunks, history, facts | answer, confidence, source | weak context → refusal (not an error); LLM failure → retry → fallback |
| `fallback_node` | error, chunks | answer | deterministic text, no LLM |
| `save_memory` | question, answer | store | logged, never fails the request |

## Trade-offs (each backed by a measurement from Days 8–20)

| Choice | Benefit | Cost / risk |
|---|---|---|
| Rules before LLM for routing and tools | free, deterministic, 100 % route accuracy on 22 labelled messages | complexity split 93 %; natural-language arithmetic ("15 % of 240") needs `LLM_ROUTING=1` |
| Refuse before the LLM when retrieval is weak | 0 % hallucination on 12 unanswerable/adversarial cases; no wasted call | threshold needs recalibration when embeddings change (Day 9 found a false refusal) |
| Sibling-chunk expansion + wide margin for complex questions | eval accuracy 82 % → 100 % (Day 13) | 2–3× more context tokens on those questions |
| One retry layer (tenacity) with `OPENAI_MAX_RETRIES=0` | predictable latency, visible retries | worst case ≈ attempts × timeout (≈ 60 s) |
| LLM judge + keyword checks | catches paraphrase and groundedness problems | same model family as the system; small, easy dataset |
| SQLite memory | durable, transactional, zero infrastructure | single node; Redis/Postgres for multi-server |
| Prompt v1 kept over stricter v2 | shorter, same quality (tie on 36 cases) | eval cannot rank strong systems |

## Data notes

77 chunks from 53 short documents (3 of them deliberately fictional: Lumaria, Nerion Desert, Port Azure – used to test that answers come from the KB, not from world knowledge). Chunks carry `topic` and `category`; embeddings are topic-prefixed. Data is small and clean, so results say more about *regressions* than about scale.
