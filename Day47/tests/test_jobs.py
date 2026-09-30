"""Day 45: the job queue - lifecycle, idempotency, backpressure, recovery, concurrency, failure isolation, and the HTTP API."""
import asyncio
import sqlite3
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from jobs import JobNotFound, JobQueue, JobStatus, JobStore, QueueFull
from schemas import Transaction

BASE = {"transaction_id": "t-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 216.0, "currency": "ILS", "country": "IL",
        "merchant_category": "groceries", "customer_type": "returning", "payment_method": "card", "customer_age_days": 400,
        "prior_chargebacks": 0}


def tx(i=1, **changes) -> Transaction:
    return Transaction(**{**BASE, "transaction_id": f"t-{i}", **changes})


def result_of(transaction: Transaction):
    return SimpleNamespace(to_dict=lambda: {"decision": {"action": "route"}, "transaction_id": transaction.transaction_id})


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "jobs.db")


def make_queue(store, processor=None, workers=2, max_size=10):
    async def default(t):
        await asyncio.sleep(0)
        return result_of(t)
    return JobQueue(store, processor or default, workers=workers, max_size=max_size)


def run(coro):
    return asyncio.run(coro)


# --- store -------------------------------------------------------------------------------------------------------------------------
def test_create_get_and_transitions(store):
    job = store.create(tx(), simulate_delay_s=0)
    assert job.status is JobStatus.QUEUED and job.job_id.startswith("job_") and job.attempts == 0
    store.mark_processing(job.job_id)
    processing = store.get(job.job_id)
    assert processing.status is JobStatus.PROCESSING and processing.attempts == 1 and processing.started_at
    store.mark_done(job.job_id, {"x": 1})
    done = store.get(job.job_id)
    assert done.status is JobStatus.DONE and done.result == {"x": 1} and done.finished_at >= done.started_at
    d = done.to_dict()
    assert d["queued_ms"] >= 0 and d["processing_ms"] >= 0 and d["result"] == {"x": 1} and d["error"] is None


def test_failed_jobs_keep_their_error(store):
    job = store.create(tx())
    store.mark_failed(job.job_id, "boom")
    assert store.get(job.job_id).status is JobStatus.FAILED and store.get(job.job_id).error == "boom"


def test_unknown_job_id(store):
    with pytest.raises(JobNotFound):
        store.get("job_nope")


def test_counts_and_unfinished(store):
    a, b, c = store.create(tx(1)), store.create(tx(2)), store.create(tx(3))
    store.mark_processing(b.job_id)
    store.mark_done(c.job_id, {})
    assert store.counts() == {"queued": 1, "processing": 1, "done": 1, "failed": 0}
    assert store.unfinished() == [a.job_id, b.job_id]


def test_store_survives_reopening(tmp_path):
    path = tmp_path / "j.db"
    job = JobStore(path).create(tx())
    assert JobStore(path).get(job.job_id).transaction["transaction_id"] == "t-1"


def test_sql_injection_in_ids_is_harmless(store):
    evil = tx(1, transaction_id="x-1")  # ids are pattern-validated by the model; the store also uses parameters
    job = store.create(evil)
    with pytest.raises(JobNotFound):
        store.get(job.job_id + "'; DROP TABLE jobs;--")
    assert store.get(job.job_id)


# --- queue: happy path ----------------------------------------------------------------------------------------------------------------
def test_jobs_are_processed_and_results_stored(store):
    async def go():
        q = make_queue(store)
        await q.start()
        jobs = [q.submit(tx(i))[0] for i in range(6)]
        await q.drain()
        await q.stop()
        return jobs
    jobs = run(go())
    for job in jobs:
        done = store.get(job.job_id)
        assert done.status is JobStatus.DONE and done.result["decision"]["action"] == "route" and done.attempts == 1


def test_submit_returns_before_processing_happens(store):
    async def go():
        q = make_queue(store)                                    # workers not started: nothing can process yet
        job, is_new = q.submit(tx())
        return job, is_new, q.queue.qsize()
    job, is_new, depth = run(go())
    assert is_new and job.status is JobStatus.QUEUED and depth == 1


def test_a_slow_job_does_not_block_the_others(store):
    """Two 1.0 s jobs and eight instant ones on 4 workers: the instant ones finish long before the slow ones are done."""
    async def go():
        async def processor(t):
            await asyncio.sleep(1.0 if t.transaction_id in ("t-0", "t-1") else 0)
            return result_of(t)

        q = make_queue(store, processor, workers=4)
        await q.start()
        started = time.perf_counter()
        for i in range(10):
            q.submit(tx(i))
        while store.counts()["done"] < 8 and time.perf_counter() - started < 0.9:      # poll instead of guessing a fixed delay
            await asyncio.sleep(0.02)
        fast_done_at = time.perf_counter() - started
        finished_early = store.counts()["done"]
        await q.drain()
        total = time.perf_counter() - started
        await q.stop()
        return finished_early, fast_done_at, total
    finished_early, fast_done_at, total = run(go())
    assert finished_early == 8 and fast_done_at < 0.9          # the instant jobs did not wait for the slow ones
    assert total < 1.7                                          # the two slow jobs ran side by side (~1 s), not one after the other (2 s)


def test_workers_process_jobs_concurrently(store):
    async def go():
        async def processor(t):
            await asyncio.sleep(0.2)
            return result_of(t)
        q = make_queue(store, processor, workers=5)
        await q.start()
        started = time.perf_counter()
        for i in range(5):
            q.submit(tx(i))
        await q.drain()
        elapsed = time.perf_counter() - started
        await q.stop()
        return elapsed
    assert run(go()) < 0.5                                       # 5 jobs x 0.2 s in ~0.2 s, not 1.0 s


def test_simulated_delay_is_applied_before_processing(store):
    async def go():
        q = make_queue(store)
        await q.start()
        started = time.perf_counter()
        q.submit(tx(), simulate_delay_s=0.3)
        await q.drain()
        elapsed = time.perf_counter() - started
        await q.stop()
        return elapsed
    assert run(go()) >= 0.3


# --- idempotency & backpressure ----------------------------------------------------------------------------------------------------------
def test_same_transaction_id_returns_the_existing_job(store):
    async def go():
        q = make_queue(store)
        first, new1 = q.submit(tx())
        second, new2 = q.submit(tx())
        return first, new1, second, new2, q.queue.qsize()
    first, new1, second, new2, depth = run(go())
    assert new1 and not new2 and first.job_id == second.job_id and depth == 1 and store.counts()["queued"] == 1


def test_failed_jobs_can_be_resubmitted(store):
    async def go():
        q = make_queue(store)
        first, _ = q.submit(tx())
        store.mark_failed(first.job_id, "x")
        second, is_new = q.submit(tx())
        return first, second, is_new
    first, second, is_new = run(go())
    assert is_new and second.job_id != first.job_id


def test_full_queue_rejects_with_429_instead_of_growing(store):
    async def go():
        q = make_queue(store, max_size=3)
        for i in range(3):
            q.submit(tx(i))
        with pytest.raises(QueueFull) as exc:
            q.submit(tx(99))
        return exc.value.status_code, store.counts()["queued"], q.queue.qsize()
    assert run(go()) == (429, 3, 3)                              # the rejected job was never even recorded


# --- failure isolation & recovery -------------------------------------------------------------------------------------------------------------
def test_a_crashing_job_is_marked_failed_and_the_worker_survives(store):
    async def go():
        async def processor(t):
            if t.transaction_id == "t-1":
                raise RuntimeError("model exploded")
            return result_of(t)

        q = make_queue(store, processor, workers=1)
        await q.start()
        bad, good = q.submit(tx(1))[0], q.submit(tx(2))[0]
        await q.drain()
        await q.stop()
        return bad, good
    bad, good = run(go())
    assert store.get(bad.job_id).status is JobStatus.FAILED and "model exploded" in store.get(bad.job_id).error
    assert store.get(good.job_id).status is JobStatus.DONE                       # the same single worker went on to the next job


def test_unfinished_jobs_are_recovered_after_a_restart(store):
    queued, interrupted, finished = store.create(tx(1)), store.create(tx(2)), store.create(tx(3))
    store.mark_processing(interrupted.job_id)                                    # the service died while processing this one
    store.mark_done(finished.job_id, {"old": True})

    async def go():
        q = make_queue(store)
        await q.start()
        await q.drain()
        await q.stop()
    run(go())
    assert store.get(queued.job_id).status is JobStatus.DONE and store.get(interrupted.job_id).status is JobStatus.DONE
    assert store.get(interrupted.job_id).attempts == 2                           # processed twice: at-least-once semantics
    assert store.get(finished.job_id).result == {"old": True}                    # finished jobs are left alone


def test_a_job_finished_before_re_enqueue_is_not_processed_again(store):
    calls = []

    async def go():
        async def processor(t):
            calls.append(t.transaction_id)
            return result_of(t)
        q = make_queue(store, processor)
        job = store.create(tx())
        store.mark_done(job.job_id, {"x": 1})
        await q.start()
        q.queue.put_nowait(job.job_id)                                           # a duplicate delivery
        await q.drain()
        await q.stop()
    run(go())
    assert calls == []


def test_stop_cancels_workers_cleanly(store):
    async def go():
        q = make_queue(store)
        await q.start()
        tasks = list(q._tasks)
        await q.stop()
        return [t.done() for t in tasks], q._tasks
    done, remaining = run(go())
    assert all(done) and remaining == []


def test_stats_report_depth_capacity_workers_and_counts(store):
    async def go():
        q = make_queue(store, workers=3, max_size=7)
        q.submit(tx(1))
        return q.stats()
    assert run(go()) == {"queue_depth": 1, "queue_capacity": 7, "workers": 3, "jobs": {"queued": 1, "processing": 0, "done": 0, "failed": 0}}


# --- HTTP API --------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    async def fast_processor(t):
        await asyncio.sleep(0.01)
        return result_of(t)

    monkeypatch.setattr(main, "arun_decision_graph", fast_processor)
    with TestClient(main.app) as c:                                              # `with` runs the lifespan: workers start
        yield c


def wait_for(client, job_id, status="done", timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/status/{job_id}").json()
        if body["status"] == status:
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not reach {status}: {body}")


def test_submit_returns_202_with_a_status_url_then_the_result_appears(client):
    r = client.post("/jobs", json={"transaction": BASE})
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["duplicate"] is False
    body = wait_for(client, r.json()["job_id"])
    assert body["result"]["decision"]["action"] == "route" and body["attempts"] == 1 and body["processing_ms"] >= 0
    assert client.get(r.json()["status_url"]).json()["status"] == "done"


def test_duplicate_submission_returns_200_and_the_same_job(client):
    first = client.post("/jobs", json={"transaction": BASE}).json()
    second = client.post("/jobs", json={"transaction": BASE})
    assert second.status_code == 200 and second.json()["duplicate"] is True and second.json()["job_id"] == first["job_id"]


def test_invalid_transactions_are_rejected_before_queueing(client):
    assert client.post("/jobs", json={"transaction": {**BASE, "amount": -1}}).status_code == 422
    assert client.get("/jobs").json()["jobs"] == {"queued": 0, "processing": 0, "done": 0, "failed": 0}


def test_unknown_status_id_is_404(client):
    assert client.get("/status/job_nope").status_code == 404


def test_simulated_delay_is_refused_unless_enabled(client, settings_override):
    assert client.post("/jobs", json={"transaction": BASE, "simulate_delay_s": 1}).status_code == 422
    settings_override(allow_simulated_delay=True)
    assert client.post("/jobs", json={"transaction": {**BASE, "transaction_id": "d-1"}, "simulate_delay_s": 0.1}).status_code == 202
    assert client.post("/jobs", json={"transaction": {**BASE, "transaction_id": "d-2"}, "simulate_delay_s": 99}).status_code == 422


def test_queue_stats_endpoint(client):
    ids = [client.post("/jobs", json={"transaction": {**BASE, "transaction_id": f"s-{i}"}}).json()["job_id"] for i in range(3)]
    for job_id in ids:
        wait_for(client, job_id)
    stats = client.get("/jobs").json()
    assert stats["jobs"]["done"] == 3 and stats["workers"] == 16 and stats["queue_capacity"] == 100


def test_job_endpoints_need_the_api_key_when_configured(client, settings_override):
    settings_override(app_api_key="s3cret")
    assert client.post("/jobs", json={"transaction": BASE}).status_code == 401
    assert client.get("/status/job_x").status_code == 401 and client.get("/jobs").status_code == 401
    assert client.post("/jobs", json={"transaction": BASE}, headers={"X-API-Key": "s3cret"}).status_code == 202


def test_queue_not_running_gives_503_not_a_crash():
    plain = TestClient(main.app)                                                  # no `with`: lifespan never ran
    if hasattr(main.app.state, "jobs"):
        del main.app.state.jobs
    assert plain.post("/jobs", json={"transaction": BASE}).status_code == 503


def test_429_is_returned_over_http_when_the_queue_is_full(monkeypatch, settings_override):
    settings_override(job_queue_max=2, job_workers=1)
    gate = asyncio.Event

    async def stuck(t):
        await asyncio.sleep(30)                                                    # the single worker is busy for the whole test
        return result_of(t)

    monkeypatch.setattr(main, "arun_decision_graph", stuck)
    with TestClient(main.app) as c:
        codes = [c.post("/jobs", json={"transaction": {**BASE, "transaction_id": f"q-{i}"}}).status_code for i in range(6)]
    assert codes.count(202) >= 2 and 429 in codes and gate is asyncio.Event


def test_sqlite_row_is_a_plain_json_document(store):
    job = store.create(tx())
    with sqlite3.connect(store.path) as db:
        (payload,) = db.execute("SELECT transaction_json FROM jobs WHERE job_id=?", (job.job_id,)).fetchone()
    assert Transaction.model_validate_json(payload).transaction_id == "t-1"


def test_async_client_can_drive_the_api_end_to_end(monkeypatch):
    async def fast(t):
        return result_of(t)

    monkeypatch.setattr(main, "arun_decision_graph", fast)

    async def go():
        async with main.lifespan(main.app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
                job = (await client.post("/jobs", json={"transaction": BASE})).json()
                for _ in range(100):
                    body = (await client.get(f"/status/{job['job_id']}")).json()
                    if body["status"] == "done":
                        return body
                    await asyncio.sleep(0.02)
    assert run(go())["result"]["transaction_id"] == "t-1"
