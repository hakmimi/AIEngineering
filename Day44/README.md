# Day 44 – Async API Handling

## Goal

Understand where `async` genuinely helps a service whose time is spent waiting on an LLM – and where it makes things *worse* – by building a proper async path, keeping an intentionally wrong one for comparison, and measuring all three under concurrent load.

```text
Concurrent Events → Async Client → FastAPI endpoint → Decision Agent (LLM awaited) → Responses
```

## What changed (vs Day 43)

| File | Change |
|---|---|
| `openai_client.py` | `get_async_client()` (AsyncOpenAI) |
| `resilience.py` | `aretry_call` – async retry with the same policy (backoff via `asyncio.sleep`, so other requests keep running while one waits) |
| `llm.py` | `aget_structured` – async twin of the structured LLM call (same schema, usage tracking, error classification) |
| `decision_graph.py` | the two LLM nodes are split into *prepare prompt → call → validate*; sync and async nodes share everything except the call; `build_graph(async_mode)`, `async_decision_graph`, `arun_decision_graph` (`ainvoke`); `timed` now works for coroutine nodes; audit write moved to a worker thread in the async runner |
| `main.py` | `POST /decision/async` (proper), `POST /decision/async-naive` (the anti-pattern, benchmark only); **start-up warm-up** of both LLM clients |
| `scripts/benchmark_async.py` (new) | async httpx load generator + a `/health` probe during the load; `--only`, `--label` options |
| `tests/test_async.py` (new) | 19 tests → 366 in total |

## How it was done (steps 1–10)

1. **What is async useful for?** Waiting on I/O. A decision spends ≈ 2 s awaiting the LLM and < 10 ms computing; a thread (or the event loop) is idle almost the whole time.
2. **Convert the endpoint "if appropriate"** – *only* with an awaitable LLM call. `async def` around blocking code is the classic mistake (variant C below).
3–5. **Async client with httpx, small concurrent batch, per-request latency** – `scripts/benchmark_async.py`.
6. **Sync vs async** – measured, below.
7. **Blocking graph steps** – tool lookups, rules, policy checks, template explanations are CPU-only and < 1 ms – fine on the loop. Blocking I/O: the LLM call (now awaited), the **SQLite audit write** (moved to `asyncio.to_thread`), and LLM **client creation** (~0.3 s of TLS setup, moved to start-up).
8. **What stays sync:** all rule/tool/policy code – making it async would only add overhead.
9–10. **Document / debug** – below, including two things the benchmark found.

## Measurements (live LLM, same events for every variant)

**40 events, concurrency 10** (run 1 of 3; throughput varies ±30 % between runs because the slowest LLM calls dominate the total):

| Variant | Throughput | Avg / p95 latency | `/health` during load (avg / max) |
|---|---:|---|---|
| sync, one request at a time | 0.84 req/s | 1.2 s / 2.7 s | 11 / 95 ms |
| **sync `def` endpoint** (FastAPI thread pool) | **5.9 – 7.6 req/s** | 1.1 – 1.2 s / 2.2 – 2.7 s | 10 / 30 ms |
| **async endpoint** (AsyncOpenAI + `ainvoke`) | **4.4 – 6.7 req/s** | 1.3 s / 2.6 – 2.9 s | 9 / 24 ms (after warm-up) |
| `async def` calling blocking code (anti-pattern) | **0.76 – 0.89 req/s** | **11 – 13 s / 13 – 16 s** | **6.4 – 7.4 s avg, 13 – 16 s max** |

**120 events, concurrency 100** (more requests in flight than the default 40-thread pool):

| Variant | Throughput | Avg / p95 | `/health` avg / max |
|---|---:|---|---|
| sync thread pool | 14.6 req/s | 4.2 s / 6.2 s | 151 ms / **3.9 s** |
| **async** | **22.9 req/s** | 3.0 s / 4.4 s | 63 ms / 0.6 s |

## Conclusions

1. **FastAPI's sync endpoints already scale** through the thread pool: 10 concurrent requests ≈ 7× the sequential throughput. Async brings **no gain at modest concurrency** – the two are within measurement noise.
2. **Async wins when in-flight requests exceed the thread pool** (40 by default): at 100 concurrent requests the async path served ≈ 1.6× the throughput with lower tail latency, and `/health` stayed responsive (0.6 s max vs 3.9 s) because health checks did not have to queue behind exhausted threads.
3. **The anti-pattern is catastrophic**: `async def` + blocking call ⇒ the event loop freezes, requests are processed one at a time (throughput back to the sequential 0.8 req/s) and even `/health` waits ≈ 13 s. A deterministic offline test reproduces this with sleeps (5 × 0.2 s takes ≥ 1 s vs ≈ 0.2 s).
4. **LLM latency is special**: it is long (1–4 s), highly variable (p95 ≈ 2× p50), not under our control and billed per call – so the useful levers are concurrency, timeouts/retries (with async backoff) and skipping the call (Day 39's fast path), not micro-optimising our own code.
5. **Two hidden loop-blockers found by measuring**: lazy creation of the async client (a 0.3 s freeze on the first request, visible as `/health` max 350 ms) → warm-up at start-up; the SQLite audit write inside the loop → worker thread.

**Decision:** keep both. `POST /decision` (sync) is the default – simplest, robust, fine to ~40 concurrent decisions per worker; `POST /decision/async` is the choice for high concurrency. The anti-pattern endpoint stays only as a documented benchmark counter-example.

## Caveats

One machine (client and server compete for CPU), one LLM provider, throughput numbers vary run to run (shown as ranges); "concurrency 100" is bounded by the provider's rate limits in real deployments.

## Run & test

```bash
cd Day44
python -m scripts.benchmark_async --n 40 --concurrency 10 --seed 11                      # live, ~$0.15
python -m scripts.benchmark_async --n 120 --concurrency 100 --seed 12 --only "pool,proper" --label high
python -m pytest                                                                        # 366 offline tests
```
