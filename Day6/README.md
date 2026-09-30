# Day 6 – Routing + Latency

## Goal

Make the system **decide when NOT to use AI** ("Good AI systems decide when NOT to use AI"):

- add a decision layer in front of RAG so trivial input never costs an embedding or an LLM call
- make latency visible: total per request and per pipeline step
- shrink the prompt to cut tokens (cost) and response time

```text
Query → Router ─┬─ skip / clarify → direct answer (0 API calls)
                └─ rag_simple | rag_complex → Retrieve → Validate → LLM → Response (+ timings)
```

## What changed (vs Day 5)

| File | Change |
|---|---|
| `router.py` (new) | `route_query()` returns a `Route(name, top_k, reason, direct_answer)` using pure rules |
| `timing.py` (new) | `StepTimer` – context-manager profiler, `report()` and `slowest()` |
| `rag.py` | Calls the router first; times `routing`, `retrieval`, `prompt`, `llm`; response now includes `route` and `timings`; prompt shortened |
| `main.py` | HTTP middleware measures full request latency, adds `X-Process-Time-Ms` header and an `http …` log line |
| `config.py` | `MIN_QUERY_WORDS`, `COMPLEX_QUERY_WORDS`, `SLOW_REQUEST_MS` |
| `tests/test_routing_latency.py` (new) | 12 tests: routing table, zero-cost skip paths, timing steps, prompt size, latency header |

## How it was implemented

1. **Routing rules** (`router.py`, evaluated in this order):
   - smalltalk (`hello`, `thanks`, `bye`, ≤ 4 words) → `skip`, canned reply, **no embedding, no LLM**
   - fewer than `MIN_QUERY_WORDS` words → `clarify`, ask the user to rephrase
   - long (> `COMPLEX_QUERY_WORDS`) or contains reasoning markers (`why`, `how`, `compare`, `and` …) → `rag_complex`, `top_k ≥ 6`
   - otherwise → `rag_simple`, `top_k ≤ 3`
   
   Smalltalk is checked *before* the length check: a bare `hello` is one word but is valid input (tests caught the wrong order).
2. **Rule-based pre-check** answers "when do we skip RAG?": only when the input can't be a knowledge question. Everything else still goes through the Day 5 validation gate.
3. **Latency** – `latency_middleware` uses `time.perf_counter()` around the whole request; `StepTimer.step()` wraps each stage and records the time even if the stage raises. Requests over `SLOW_REQUEST_MS` log a warning naming the slowest step, which is the bottleneck report.
4. **Prompt optimisation** – instructions cut from ~9 lines to 2, and chunk headers changed from `[doc_id=1 chunk_id=0]` to `[1:0]`. A test asserts the template stays under 350 characters.
5. **Decision-path logging** – `decision=route name=… reason=… top_k=…`, then `request route=… source=… timings=…`.

Example `/rag` result fields: `"route": "rag_simple", "source": "rag", "timings": {"routing": 0.1, "retrieval": 412.3, "prompt": 0.0, "llm": 1180.5, "total_ms": 1593.1}`. (Shape only – see caveat.)

## Run & test

```bash
cd Day6
python embedding_pipeline.py     # once, needs OPENAI_API_KEY
uvicorn main:app --reload
python -m pytest tests -q        # 33 offline tests (Day 5 suite + Day 6)
```

## Caveats

- Rule-based routing is deliberately simple; the marker `and` sends many questions to the complex path. Refine it with real traffic (plan step 7) – or replace it with a classifier later.
- Latency numbers in real conditions are not measured yet: OpenAI was unreachable from the build environment (SSL certificate error), so only the timing *mechanism* is tested.
