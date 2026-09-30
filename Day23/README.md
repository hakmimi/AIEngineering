# Day 23 – Observability / Logging / Tracing

## Goal

Make every request explainable after the fact: one **standard log format**, a **request id** that ties every line of a request together, and events for routing, retrieval, tools, node latency and errors – without logging users' text.

```text
Client → Request ID → API → Graph nodes → structured JSON logs (+ timings) → Response (X-Request-ID, X-Process-Time-Ms)
```

## What changed (vs Day 22)

| File | Change |
|---|---|
| `observability.py` (new) | `JsonFormatter` (one JSON object per line; `LOG_FORMAT=text` for humans), `RequestIdFilter` + `request_id_var` (ContextVar), `log_event()` (readable text *and* structured fields), `redact()` (user text hidden unless `LOG_USER_TEXT=1`), `summarize()`, idempotent `configure_logging()` |
| `main.py` | Middleware: honours/generates `X-Request-ID`, logs `request_start` / `request_end` (status, latency), sets `X-Request-ID` and `X-Process-Time-Ms`; error bodies now include `request_id` |
| `graph.py` | `graph_node` (node, ms), `graph_route` (route, query_type, reason, routed_by), `graph_tool_selected`, `graph_node_failed` (with context), `graph_done` (trace + all timings), memory events – as structured events |
| `retrieval.py` | `retrieval` event: filters, query length, kept, best score, `embed_ms` vs `search_ms`, and **metadata of every retrieved chunk** (doc, chunk, topic, score, expanded) |
| `tools.py` | `tool_call` event: tool, args, ok/error, output summary, ms |
| `scripts/log_demo.py` (new) | 5 live requests → `data/logs/sample_requests.jsonl` + a per-request reconstruction |
| `tests/test_observability.py` (new) | 20 tests (242 pass) |

## How it was implemented

1. **Standard log format** – JSON lines with fixed keys `ts` (UTC ISO ms), `level`, `logger`, `event`, `request_id` plus event-specific fields. Machine-parseable (grep/jq/Loki/CloudWatch) yet `log_event()` also writes a normal `event key=value` message for humans/pytest.
2. **How do we trace one request?** A `ContextVar` holds the id; a logging *filter* stamps it on **every** record from any module/thread – no function needs a `request_id` parameter. Starlette copies the context into worker threads, so sync endpoints and LangGraph nodes see it too. A client-supplied `X-Request-ID` is honoured so a caller can correlate its own logs.
3. **Latency** – per request (`request_end.latency_ms`), per node (`graph_node.ms`), and inside retrieval (`embed_ms` vs `search_ms`); `graph_done.timings` carries the whole breakdown.
4. **Decisions** – `graph_route` answers *"why did the system choose this path?"* (route, complexity, reason, rule vs LLM); `graph_tool_selected` and `tool_call` answer *"which tools were called and why?"*.
5. **Privacy** – questions/rewrites are logged as `<N chars>` unless `LOG_USER_TEXT=1`; a test asserts the question text never appears by default.
6. **Errors with request id** – node failures log type/retryable/route/query_type; unhandled exceptions are logged with a traceback and the same `request_id` that is returned to the client, so a user report ("request 3f9a…") maps to one log slice.

## Bug found and fixed

`logger.exception()` inside a FastAPI *exception handler* logs `NoneType: None` – there is no active `except` block there, so every earlier version (Days 5–22) lost the traceback of unhandled errors. Fixed with `logger.error(..., exc_info=exc)`; a test now checks the traceback is present.

## Live result – 5 requests, 45 log lines (`data/logs/sample_requests.jsonl`)

| Request id | Route | Latency | Slowest node | Reading |
|---|---|---:|---|---|
| demo-1 `hello` | direct/simple | 41 ms | route_query 0.7 ms | no API calls |
| demo-2 `Where is Masada?` | rag/simple | 2650 ms | retrieve_context 1473 ms | the **embedding call** is the bottleneck, not FAISS (`search_ms` ≈ 1 ms) |
| demo-3 `Compare Tel Aviv and Haifa` | rag/complex | 2863 ms | call_llm 2662 ms | 6+ chunks → long prompt/answer |
| demo-4 `12*(3+4)` | tool/simple | 1349 ms | tool_answer 1320 ms | the tool ran in 0.9 ms; phrasing its result costs 1.3 s |
| demo-5 `capital of France?` | rag/simple | 290 ms | retrieve_context 275 ms | weak context → refusal before the LLM |

Every line of each request carries its `demo-N` id, so `jq 'select(.request_id=="demo-3")'` reconstructs the flow.

## Run & test

```bash
cd Day23
python -m pytest tests -q
python -m scripts.log_demo
LOG_FORMAT=text uvicorn main:app          # human-readable local logs
LOG_USER_TEXT=1 uvicorn main:app          # include user text (debugging only)
curl -i -H "X-Request-ID: my-trace-1" localhost:8000/health
```
