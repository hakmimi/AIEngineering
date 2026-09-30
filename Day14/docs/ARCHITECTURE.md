# Architecture – Israel Knowledge Assistant (RAG + tools + memory)

## One-line summary

A FastAPI service that answers questions about a small Israel knowledge base using retrieval-augmented generation, with rule-based routing, tools, per-session memory, guardrails against hallucination, and an evaluation harness.

## Request flow

```text
Client
  │  POST /ask {session_id, query}
  ▼
FastAPI (routes.py)  ── auth + rate limit (security.py) ── validation (schemas.py)
  ▼
assistant.ask()
  ├─ Router (router.py)      greeting → canned reply | too short → clarify        (0 API calls)
  ├─ Rule decision           arithmetic → calculate | "list topics" → list_topics (0 decision calls)
  │     └─ Tool (tools.py) → phrase answer from tool result (1 LLM call)
  └─ chat()  (chat.py)
        ├─ Memory (memory.py)   load last turns for session_id
        ├─ Rewrite follow-up    LLM, only if history exists AND question looks context-dependent
        ├─ Retrieval (retrieval.py)
        │     embed query → FAISS top-k → keyword/topic re-rank → metadata filter
        │     → score floor + relative cutoff → sibling-chunk expansion
        ├─ Gate (rag.validate_context)   best score < threshold → refuse WITHOUT calling the LLM
        ├─ Prompt (prompts.py)   grounded, cite sources, memory block labelled "not a fact source"
        └─ LLM (llm.py)          structured JSON output; provider errors → fallback answer
  ▼
Save turn to memory → JSON response (answer, source, route, timings, retrieved_chunks, session/tool info)
```

Also available: `/rag` (single-step), `/rag/multistep` (analyze → retrieve → extract → compose, Day 10), `/ask/tools` (LLM picks the tool, Day 11), `/chat`, `/search`, `/session/{id}`, `/health`, `/ready`.

## Modules (one job each)

| Module | Responsibility |
|---|---|
| `main.py` / `routes.py` / `schemas.py` | app wiring, endpoints, request models |
| `assistant.py` | top-level orchestration (tool vs chat) |
| `chat.py` / `memory.py` | multi-turn: history store, follow-up rewriting |
| `router.py` | deterministic pre-checks and query complexity |
| `tool_agent.py` / `tools.py` | tool decision layer, tool registry + safe execution |
| `pipeline.py` | optional multi-step reasoning pipeline |
| `retrieval.py` / `vector_store.py` | search, ranking, filtering, FAISS persistence |
| `rag.py` / `prompts.py` | context building, gate, prompts, response shape |
| `llm.py` / `embeddings.py` / `openai_client.py` | the only files that talk to OpenAI |
| `security.py`, `config.py`, `errors.py`, `timing.py` | cross-cutting |
| `scripts/` | evaluation (`evaluate`), retrieval quality, retrieval comparison, pipeline demo |

## Key design decisions

| Decision | Why | Evidence |
|---|---|---|
| Refuse before the LLM when retrieval is weak | cheapest and safest hallucination control | hallucination rate 0 % on 5 unanswerable eval cases |
| Rules before LLM for routing/tools | free, deterministic, testable | greetings/arithmetic cost 0–1 LLM calls |
| FAISS with normalised vectors | cosine scale stays the same as thresholds; persisted index | ≈ 65× faster search (Day 8) |
| Topic-prefixed embeddings + topic boost + relative cutoff | precision of retrieved context | precision 0.43 → 0.91 (Day 9) |
| Sibling-chunk expansion | answers often live in a neighbour chunk | eval accuracy 82 % → 100 % (Day 13) |
| Provider errors → typed exceptions → fallback answers | API never returns a stack trace | tests for every failure path |
| Everything LLM-related mockable | 140+ offline tests, no key needed | `tests/` |

## Known limits

- 77 chunks / 53 documents: exact search is right; approximate indexes are unnecessary at this size.
- Eval set (22 cases) is small and keyword-scored; answers are not bit-for-bit stable across runs even at temperature 0 (17/22 identical, 22/22 same verdict).
- Memory and rate limiting are in-process; multi-worker deployment needs Redis/DB.
- The latency floor is two network calls (embedding ≈ 0.3–1.4 s, LLM ≈ 1–3 s).
