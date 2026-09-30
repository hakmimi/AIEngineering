"""Sync vs async under concurrent load (live LLM).

    python -m scripts.benchmark_async --n 40 --concurrency 10 --seed 11

Starts a local server (isolated audit db) and sends the SAME events with an async httpx client to:
  sync      POST /decision              (def endpoint -> FastAPI thread pool)
  async     POST /decision/async        (AsyncOpenAI + graph.ainvoke)
  naive     POST /decision/async-naive  (async def calling blocking code - the anti-pattern)
while a probe measures how long GET /health takes DURING the load (a blocked event loop shows up there).
Also runs the sync endpoint at concurrency 1 as the sequential reference.
"""
import argparse
import asyncio
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
VARIANTS = [("sync (sequential, concurrency 1)", "/decision", 1), ("sync (thread pool)", "/decision", None),
            ("async (proper)", "/decision/async", None), ("async-naive (blocks the loop)", "/decision/async-naive", None)]


async def run_variant(base_url: str, path: str, events: list[dict], concurrency: int) -> dict:
    latencies, statuses, health = [], [], []
    semaphore = asyncio.Semaphore(concurrency)
    done = asyncio.Event()

    async with httpx.AsyncClient(base_url=base_url, timeout=120) as client:
        async def one(item):
            async with semaphore:
                started = time.perf_counter()
                r = await client.post(path, json=item["event"])
                latencies.append((time.perf_counter() - started) * 1000)
                statuses.append(r.status_code)

        async def probe():
            while not done.is_set():
                started = time.perf_counter()
                try:
                    await client.get("/health", timeout=60)
                    health.append((time.perf_counter() - started) * 1000)
                except httpx.HTTPError:
                    health.append(60000.0)
                await asyncio.sleep(0.1)

        prober = asyncio.create_task(probe())
        started = time.perf_counter()
        await asyncio.gather(*(one(e) for e in events))
        total = time.perf_counter() - started
        done.set()
        await prober
    ordered = sorted(latencies)
    return {"path": path, "concurrency": concurrency, "events": len(events), "ok": sum(s == 200 for s in statuses),
            "total_s": round(total, 2), "throughput_rps": round(len(events) / total, 2),
            "latency_avg_ms": round(statistics.mean(latencies)), "latency_p95_ms": round(ordered[int(len(ordered) * 0.95) - 1]),
            "health_avg_ms": round(statistics.mean(health)) if health else None, "health_max_ms": round(max(health)) if health else None}


async def main_async(base_url: str, n: int, concurrency: int, seed: int, only: str = "") -> list[dict]:
    events = build_events(n, seed)
    results = []
    wanted = [w for w in only.split(",") if w]
    for name, path, level in VARIANTS:
        if wanted and not any(w in name for w in wanted):
            continue
        result = {"variant": name, **(await run_variant(base_url, path, events, level or concurrency))}
        results.append(result)
        print(f"{name:34} conc={result['concurrency']:<3} total={result['total_s']:>6}s  {result['throughput_rps']:>5} req/s  "
              f"avg={result['latency_avg_ms']:>5}ms p95={result['latency_p95_ms']:>5}ms  /health avg={result['health_avg_ms']}ms max={result['health_max_ms']}ms  ok={result['ok']}/{n}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--only", default="", help="comma-separated substrings of variant names to run, e.g. \"pool,proper\"")
    parser.add_argument("--label", default="benchmark_async")
    args = parser.parse_args()
    port = 8766
    env = {**os.environ, "AUDIT_DB_PATH": str(OUT / "bench_audit.db"), "PYTHONUNBUFFERED": "1"}
    OUT.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port), "--log-level", "warning"],
                              cwd=str(Path(__file__).resolve().parent.parent), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
            wait_until_healthy(client)
        results = asyncio.run(main_async(f"http://127.0.0.1:{port}", args.n, args.concurrency, args.seed, args.only))
        (OUT / f"{args.label}.json").write_text(json.dumps({"args": vars(args), "results": results}, indent=1), encoding="utf8")
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
