"""Live demo of the job queue: submit a burst, poll until done, and show what the caller experiences.

    python -m scripts.queue_demo --n 24 --slow 3 --workers 4

Starts a local server (isolated audit + jobs databases, ALLOW_SIMULATED_DELAY=1) so `--slow K` jobs can pretend the model takes 6 s.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx

from config import settings
from scripts.simulate import wait_until_healthy
from traffic import build_events

OUT = settings.data_dir / "simulation"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=24)
    parser.add_argument("--slow", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=21)
    args = parser.parse_args()
    port = 8767
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("queue_audit.db", "queue_jobs.db"):
        for suffix in ("", "-wal", "-shm"):
            Path(OUT / f"{name}{suffix}").unlink(missing_ok=True)
    env = {**os.environ, "AUDIT_DB_PATH": str(OUT / "queue_audit.db"), "JOBS_DB_PATH": str(OUT / "queue_jobs.db"),
           "ALLOW_SIMULATED_DELAY": "1", "JOB_WORKERS": str(args.workers), "PYTHONUNBUFFERED": "1"}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port), "--log-level", "warning"],
                              cwd=str(Path(__file__).resolve().parent.parent), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60) as client:
            wait_until_healthy(client)
            events = build_events(args.n, args.seed)
            submitted, submit_ms = {}, []
            burst_started = time.perf_counter()
            for i, item in enumerate(events):
                delay = 6.0 if i < args.slow else 0.0                       # the first K jobs are "slow"
                started = time.perf_counter()
                r = client.post("/jobs", json={"transaction": item["event"], "simulate_delay_s": delay})
                submit_ms.append((time.perf_counter() - started) * 1000)
                assert r.status_code == 202, r.text
                submitted[r.json()["job_id"]] = {"i": i, "slow": delay > 0, "scenario": item["scenario"]}
            submit_total = time.perf_counter() - burst_started
            print(f"submitted {args.n} jobs in {submit_total:.2f} s (avg {statistics.mean(submit_ms):.1f} ms, max {max(submit_ms):.1f} ms per POST)")
            print("queue right after the burst:", client.get("/jobs").json())

            finished, done_at = {}, {}
            while len(finished) < args.n and time.perf_counter() - burst_started < 300:
                for job_id in submitted:
                    if job_id in finished:
                        continue
                    body = client.get(f"/status/{job_id}").json()
                    if body["status"] in ("done", "failed"):
                        finished[job_id] = body
                        done_at[job_id] = time.perf_counter() - burst_started
                time.sleep(0.2)
            total = time.perf_counter() - burst_started
    finally:
        server.terminate()
        server.wait(timeout=10)

    fast = [finished[j] for j, m in submitted.items() if not m["slow"]]
    slow = [finished[j] for j, m in submitted.items() if m["slow"]]
    last_fast = max(done_at[j] for j, m in submitted.items() if not m["slow"])
    sequential = sum(f["processing_ms"] for f in finished.values()) / 1000
    summary = {
        "jobs": args.n, "workers": args.workers, "slow_jobs": args.slow, "failed": sum(f["status"] == "failed" for f in finished.values()),
        "submit_avg_ms": round(statistics.mean(submit_ms), 1), "submit_total_s": round(submit_total, 2),
        "all_done_after_s": round(total, 1), "last_fast_job_done_after_s": round(last_fast, 1),
        "sum_of_processing_s (=sequential time)": round(sequential, 1),
        "fast_queue_wait_ms": {"avg": round(statistics.mean(f["queued_ms"] for f in fast)), "max": max(f["queued_ms"] for f in fast)},
        "fast_processing_ms_avg": round(statistics.mean(f["processing_ms"] for f in fast)),
        "slow_processing_ms_avg": round(statistics.mean(f["processing_ms"] for f in slow)) if slow else None,
    }
    print(json.dumps(summary, indent=1))
    (OUT / "queue_demo.json").write_text(json.dumps(summary, indent=1), encoding="utf8")


if __name__ == "__main__":
    main()
