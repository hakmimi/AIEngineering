# Day 18 – Failure Handling / Retry / Fallback

## Goal

Make the graph **recover, not crash**: contain exceptions at node boundaries, retry only what can succeed on retry, and route every failure to a fallback node that degrades gracefully.

```text
Query → Node → success path
              ├─ transient failure → retry (backoff) → success path
              └─ still failing / non-retryable → fallback_node → honest answer (+ best evidence if we have it)
```

## What changed (vs Day 17)

| File | Change |
|---|---|
| `errors.py` | `ExternalServiceError.retryable` flag |
| `openai_client.py` | `is_retryable(exc)` – timeout / connection / 429 / 5xx are retryable; bad key / invalid request are not |
| `embeddings.py`, `llm.py` | set `retryable` from the provider exception; malformed JSON is retryable |
| `resilience.py` (new) | `retry_call()` using **tenacity**: capped attempts, exponential backoff, retries only retryable `ExternalServiceError`, logs every retry, re-raises at the end |
| `graph.py` | `safe(name)` node boundary (exception → `state["error"]` + contextual log); `fallback_node`; `or_fallback(...)` conditional edges after every failing node; retries around retrieval and LLM; response includes `error` |
| `prompts.py` | `render_degraded_answer()` – what to say when the system can't finish |
| `config.py` | `RETRY_ATTEMPTS` (3), `RETRY_BASE_DELAY` (0.5 s); **`OPENAI_MAX_RETRIES` default 2 → 0** (see below) |
| `embedding_pipeline.py` | bulk embedding wrapped in `retry_call` |
| `scripts/failure_drill.py` (new), `docs/graph.md` | live drill, diagram + failure table |
| `tests/test_failures.py` (new) | 14 failure-injection tests (191 pass) |

## How it was implemented

1. **Failure points** – listed per node in `docs/graph.md` (embedding API, index, LLM, tools, plus bugs).
2. **try/except at the node boundary** – `safe()` wraps each failing node: on *any* exception it logs `graph_node_failed node=… type=… retryable=… route=… query_type=… question_len=…` (context that helps debugging, no user text) and stores `state["error"]`.
3. **Fallback edge** – after each such node a conditional edge sends the run to `fallback_node` if `error` is set.
4. **When to retry?** Only when a retry can plausibly succeed: timeouts, connection errors, 429, 5xx, malformed output. Not for auth errors, bad requests, or our own bugs. Waits 0.5 s, 1 s (exponential), max 3 attempts.
5. **Safe answer when uncertain** – the fallback text is deterministic (no LLM – it may be what failed). If retrieval worked but the LLM did not, the answer also shows the best retrieved passage: degraded, but useful and never invented.
6. **Expected outcomes are not failures** – a weak-context refusal (`no_context`) or a tool error like `1/0` stays on the normal path.

## Finding: stacked retries multiply latency

The first live drill (server unreachable) took **25 s**: the OpenAI SDK retried each request 2× *inside* each of our 3 attempts. Fix: one retry layer – `OPENAI_MAX_RETRIES=0`, all retrying done (and logged) by `retry_call`.

## Live drills (real failures, not mocks)

| Drill | Result |
|---|---|
| Invalid API key (`AuthenticationError`) | **not retried**; trace `… retrieve_context → fallback_node`; 2.1 s; `retryable=False` in the response |
| Connection refused (`OPENAI_BASE_URL=http://127.0.0.1:9`) | retried with waits 0.5 s and 1.0 s, then fallback; 8.9 s total (each refused connect ≈ 2.4 s on Windows) |
| Normal request | `rag`, 2.9 s, no error |

Offline tests cover: recovery after 1 transient failure (LLM and retrieval), give-up after max attempts, non-retryable and non-`ExternalServiceError` exceptions not retried, degraded answer with evidence, tool failure, an unexpected `ZeroDivisionError` inside a node, refusal-is-not-an-error.

## Run & test

```bash
cd Day18
python -m pytest tests -q
OPENAI_API_KEY=sk-invalid python -m scripts.failure_drill
OPENAI_BASE_URL=http://127.0.0.1:9 python -m scripts.failure_drill
```

Worst-case latency budget: attempts × (timeout `OPENAI_TIMEOUT_SECONDS`=20 s) + backoff ≈ 61 s for a call that keeps timing out – reduce attempts or timeout if that is too long for your use case.
