"""Queue-based (event-driven) decisions: submit fast, process in the background, poll for the result.

    Submit Event -> Queue -> Worker -> Decision Agent -> Store status -> Status endpoint

Why: an AI decision can take seconds; the caller should not have to hold a connection open for it, and a burst of events should
be absorbed by a queue instead of overloading the model. Ingestion and processing are decoupled: POST /jobs only validates,
records and enqueues (milliseconds); a small pool of workers does the slow part.

Design choices (each has a test):
* the job table (SQLite) is the source of truth; the in-memory asyncio queue only carries job ids, so a restart loses nothing:
  on start-up unfinished jobs are re-enqueued;
* the queue is BOUNDED - when full, submissions fail fast with 429 (backpressure) instead of piling up without limit;
* idempotent by transaction_id: submitting the same transaction twice returns the existing job (a retrying client must not
  create two decisions for one payment);
* workers never crash: any exception marks that one job `failed` and the worker carries on.
"""
import asyncio
import json
import logging
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from config import settings
from errors import AppError
from observability import log_event
from schemas import Transaction

logger = logging.getLogger("jobs")


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class JobNotFound(AppError):
    def __init__(self, job_id: str):
        super().__init__(f"no job '{job_id}'", status_code=404)


class QueueFull(AppError):
    def __init__(self):
        super().__init__("the job queue is full - retry later", status_code=429)


@dataclass
class Job:
    job_id: str
    transaction_id: str
    status: JobStatus
    transaction: dict
    result: dict | None
    error: str | None
    created_at: float
    started_at: float | None
    finished_at: float | None
    attempts: int
    simulate_delay_s: float

    def to_dict(self) -> dict:
        now = time.time()
        return {
            "job_id": self.job_id, "transaction_id": self.transaction_id, "status": self.status.value, "attempts": self.attempts,
            "result": self.result, "error": self.error,
            "queued_ms": round(((self.started_at or now) - self.created_at) * 1000),
            "processing_ms": None if self.started_at is None else round(((self.finished_at or now) - self.started_at) * 1000),
        }


class JobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, transaction_id TEXT NOT NULL, status TEXT NOT NULL,"
                       " transaction_json TEXT NOT NULL, result_json TEXT, error TEXT, created_at REAL NOT NULL, started_at REAL,"
                       " finished_at REAL, attempts INTEGER NOT NULL DEFAULT 0, simulate_delay_s REAL NOT NULL DEFAULT 0)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_tx ON jobs(transaction_id)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        return db

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(row["job_id"], row["transaction_id"], JobStatus(row["status"]), json.loads(row["transaction_json"]),
                   json.loads(row["result_json"]) if row["result_json"] else None, row["error"], row["created_at"], row["started_at"],
                   row["finished_at"], row["attempts"], row["simulate_delay_s"])

    def create(self, tx: Transaction, simulate_delay_s: float = 0.0) -> Job:
        job_id = "job_" + uuid.uuid4().hex[:12]
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO jobs(job_id, transaction_id, status, transaction_json, created_at, simulate_delay_s) VALUES (?,?,?,?,?,?)",
                       (job_id, tx.transaction_id, JobStatus.QUEUED.value, tx.model_dump_json(), time.time(), simulate_delay_s))
        return self.get(job_id)

    def get(self, job_id: str) -> Job:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return self._job(row)

    def find_active_for_transaction(self, transaction_id: str) -> Job | None:
        """An existing job for this transaction that is not failed (idempotency)."""
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM jobs WHERE transaction_id=? AND status != ? ORDER BY created_at LIMIT 1",
                             (transaction_id, JobStatus.FAILED.value)).fetchone()
        return self._job(row) if row else None

    def mark_processing(self, job_id: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE jobs SET status=?, started_at=?, attempts=attempts+1 WHERE job_id=?", (JobStatus.PROCESSING.value, time.time(), job_id))

    def mark_done(self, job_id: str, result: dict) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE jobs SET status=?, result_json=?, finished_at=? WHERE job_id=?",
                       (JobStatus.DONE.value, json.dumps(result), time.time(), job_id))

    def mark_failed(self, job_id: str, error: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE jobs SET status=?, error=?, finished_at=? WHERE job_id=?", (JobStatus.FAILED.value, error, time.time(), job_id))

    def unfinished(self) -> list[str]:
        """Ids of jobs that were queued or being processed when the service stopped, oldest first."""
        with closing(self._connect()) as db:
            return [r["job_id"] for r in db.execute("SELECT job_id FROM jobs WHERE status IN (?,?) ORDER BY created_at",
                                                    (JobStatus.QUEUED.value, JobStatus.PROCESSING.value))]

    def requeue(self, job_id: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute("UPDATE jobs SET status=?, started_at=NULL WHERE job_id=?", (JobStatus.QUEUED.value, job_id))

    def counts(self) -> dict:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        return {s.value: next((r["n"] for r in rows if r["status"] == s.value), 0) for s in JobStatus}


class JobQueue:
    """Bounded in-memory queue of job ids + a pool of async workers that run the decision agent."""

    def __init__(self, store: JobStore, processor, workers: int | None = None, max_size: int | None = None):
        self.store = store
        self.processor = processor                                   # async callable: Transaction -> AIResult-like with .to_dict()
        self.worker_count = workers or settings.job_workers
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_size or settings.job_queue_max)
        self._tasks: list[asyncio.Task] = []

    # -- producer side ---------------------------------------------------------------------------------------------------------------
    def submit(self, tx: Transaction, simulate_delay_s: float = 0.0) -> tuple[Job, bool]:
        """Returns (job, is_new). Existing job for the same transaction id -> (job, False). Full queue -> QueueFull (429)."""
        existing = self.store.find_active_for_transaction(tx.transaction_id)
        if existing is not None:
            return existing, False
        if self.queue.full():
            log_event(logger, "queue_full", level=logging.WARNING, depth=self.queue.qsize())
            raise QueueFull()
        job = self.store.create(tx, simulate_delay_s)
        self.queue.put_nowait(job.job_id)
        log_event(logger, "job_queued", job_id=job.job_id, transaction_id=tx.transaction_id, depth=self.queue.qsize())
        return job, True

    # -- consumer side -----------------------------------------------------------------------------------------------------------------
    async def _worker(self, name: str) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self._process(job_id, name)
            except Exception as exc:  # noqa: BLE001 - a worker must never die because of one bad job
                log_event(logger, "worker_error", level=logging.ERROR, worker=name, job_id=job_id, error=type(exc).__name__)
                try:
                    self.store.mark_failed(job_id, f"{type(exc).__name__}: {exc}")
                except Exception:  # noqa: BLE001
                    pass
            finally:
                self.queue.task_done()

    async def _process(self, job_id: str, worker: str) -> None:
        job = self.store.get(job_id)
        if job.status is JobStatus.DONE:
            return                                                   # re-enqueued after a restart but already finished
        self.store.mark_processing(job_id)
        started = time.perf_counter()
        if job.simulate_delay_s:
            await asyncio.sleep(job.simulate_delay_s)                # stand-in for a slow model call (awaited: other workers keep going)
        result = await self.processor(Transaction(**job.transaction))
        self.store.mark_done(job_id, result.to_dict())
        log_event(logger, "job_done", job_id=job_id, worker=worker, processing_ms=round((time.perf_counter() - started) * 1000),
                  depth=self.queue.qsize())

    async def start(self) -> None:
        """Start the workers and re-enqueue jobs left unfinished by a previous run."""
        for job_id in self.store.unfinished():
            self.store.requeue(job_id)
            if not self.queue.full():
                self.queue.put_nowait(job_id)
        self._tasks = [asyncio.create_task(self._worker(f"w{i}")) for i in range(self.worker_count)]
        log_event(logger, "queue_started", workers=self.worker_count, recovered=self.queue.qsize())

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def drain(self, timeout: float = 30.0) -> None:
        """Wait until every queued job has been processed (tests and graceful shutdown)."""
        await asyncio.wait_for(self.queue.join(), timeout)

    def stats(self) -> dict:
        return {"queue_depth": self.queue.qsize(), "queue_capacity": self.queue.maxsize, "workers": self.worker_count, "jobs": self.store.counts()}
