# Day 45 – Queue, Worker and Job Status (event-driven processing)

## Goal

Decouple *receiving* an event from *deciding* it: accept transactions instantly, absorb bursts in a queue, process them with a pool of background workers, and let callers poll for the result – and understand what such a design does to latency and failure handling.

```text
Submit Event → Queue → Worker → Decision Agent → Store Status → Status Endpoint
```

## What changed (vs Day 44)

| File | Change |
|---|---|
| `jobs.py` (new) | `JobStore` (SQLite job table = source of truth), `JobQueue` (bounded `asyncio.Queue` of job ids + worker pool), `Job`, `JobStatus` (`queued → processing → done / failed`), `JobNotFound`, `QueueFull` |
| `main.py` | `POST /jobs` (202 + `status_url`; 200 for a duplicate), `GET /status/{job_id}`, `GET /jobs` (queue stats); workers start and stop in the app lifespan; all API-key protected |
| `config.py` | `JOB_WORKERS` (default **16**), `JOB_QUEUE_MAX` (100), `JOBS_DB_PATH`, `ALLOW_SIMULATED_DELAY` (demo only) |
| `scripts/queue_demo.py` (new) | live burst: submits a batch (some "slow" jobs), polls, reports submit latency, queue wait, total time |
| `tests/test_jobs.py` (new), `tests/conftest.py` | 30 tests → 396 in total; the app's job database is redirected to a temp file in every test |

## How it was done (steps 1–10)

1. **Job/event status schema** – `queued → processing → done | failed`, plus attempts, timestamps, stored result or error; `queued_ms` and `processing_ms` are derived for the status response.
2. **In-memory queue** – a *bounded* `asyncio.Queue` that carries only job ids.
3. **Submit endpoint** – validates the `Transaction`, writes the job row, enqueues the id, returns `202` in milliseconds.
4. **Background worker** – N async worker tasks: mark processing → (optional simulated delay) → `arun_decision_graph` → store result. A crash marks *that job* failed; the worker carries on.
5. **Store job status** – SQLite (WAL) so status survives a restart.
6. **Status endpoint** – `GET /status/{id}`: status, result when done, error when failed, queue and processing time.
7–9. **Test submission / status retrieval / slow job** – 30 tests, and the live demo below.
10. **Document the event-driven flow** – this file.

Design decisions that matter (all tested):
- **Source of truth is the table, not the queue.** On start-up unfinished jobs (`queued`, or `processing` when the service died) are re-enqueued; finished ones are skipped even if delivered twice. Delivery is *at-least-once* (an interrupted job runs again, `attempts: 2`).
- **Backpressure.** A full queue answers `429` immediately instead of growing without bound (and the rejected job is never recorded).
- **Idempotency by `transaction_id`.** A client that retries a POST gets the existing job back (`200`, `duplicate: true`) – one payment must never produce two decisions.
- **Slow jobs don't block fast ones** *provided there are enough workers* – see the measurement.

## Live measurement (24 jobs, 3 of them "slow": +6 s each, real LLM for the rest)

| | 4 workers | 16 workers |
|---|---:|---:|
| `POST /jobs` (caller waits) | avg 59 ms (first request 0.8 s warm-up) | avg 76 ms |
| Time until the last *fast* job is done | 14.1 s | **5.0 s** |
| Average / max queue wait of the fast jobs | **7.6 s / 11.7 s** | **0.16 s / 1.1 s** |
| Time until everything is done | 14.3 s | 8.7 s |
| Sequential time (sum of processing) | 53.5 s | 52.9 s |
| Failed jobs | 0 | 0 |

What it shows:
- **The caller's wait shrinks from seconds to ~60 ms** – processing time (≈ 1.4 s per fast job, ≈ 7.6 s per slow one) no longer sits on the request path.
- **Head-of-line blocking is real:** with 4 workers, 3 slow jobs occupy 3 of them for 7.7 s and 21 jobs share the remaining worker – queue wait balloons to 7.6 s on average. Because workers are cheap coroutines that mostly *wait on the model*, the default is now 16; the provider's rate limit, not the worker count, is the real cap.
- The ~53 s of sequential work finishes in 8.7 s (≈ 6× faster) at 16 workers.

## Limits (what this is not)

An in-process queue: if the process dies, in-flight work is recovered from the table, but there is no multi-node scaling, no priority lanes (an obvious next step: send rule-only decisions that need no LLM to their own fast lane so a slow model call can never delay them), no dead-letter queue and no automatic retry of failed jobs. For production use a broker (Redis/RabbitMQ/SQS) and keep this table as the status store.

## Run & test

```bash
cd Day45
python -m pytest                                              # 396 offline tests
python -m scripts.queue_demo --n 24 --slow 3 --workers 16     # live, ~$0.03
# POST /jobs {"transaction": {...}}  ->  202 {"job_id": "job_...", "status_url": "/status/job_..."}
# GET  /status/job_...               ->  {"status": "done", "result": {...}, "queued_ms": ..., "processing_ms": ...}
```
