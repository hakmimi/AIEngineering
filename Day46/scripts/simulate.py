"""Traffic simulator: send events to the running decision API one by one and record what happens.

    python -m scripts.simulate --label run1 --n 100 --seed 7 --spawn      # start a local server, run, stop it
    python -m scripts.simulate --label run1 --base-url http://localhost:8000    # against a server you started yourself

Writes data/simulation/<label>.json and .csv (one row per event: scenario, decision, route, LLM status, latency, cost, ids).
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from config import settings
from traffic import build_events

OUT_DIR = settings.data_dir / "simulation"


def wait_until_healthy(client: httpx.Client, seconds: float = 30) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if client.get("/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.3)
    raise RuntimeError("the server did not become healthy in time")


def run(base_url: str, n: int, seed: int) -> list[dict]:
    rows = []
    with httpx.Client(base_url=base_url, timeout=60) as client:
        wait_until_healthy(client)
        for i, item in enumerate(build_events(n, seed)):
            started = time.perf_counter()
            try:
                response = client.post("/decision", json=item["event"], headers={"X-Request-ID": f"sim-{seed}-{i:04d}"})
                wall_ms = (time.perf_counter() - started) * 1000
                body = response.json() if response.status_code == 200 else {}
                results = body
                decision = results.get("decision", {})
                rows.append({
                    "i": i, "scenario": item["scenario"], "transaction_id": item["event"]["transaction_id"], "status": response.status_code,
                    "action": decision.get("action"), "provider": decision.get("selected_provider"),
                    "reason_codes": "|".join(decision.get("reason_codes", [])), "route": results.get("graph", {}).get("route"),
                    "llm_status": results.get("llm_status"), "fast_path": results.get("fast_path"),
                    "blocked_by": "|".join(b["policy_id"] for b in results.get("blocked_by", [])),
                    "server_ms": results.get("latency_ms"), "wall_ms": round(wall_ms, 1),
                    "llm_calls": results.get("usage", {}).get("llm_calls"), "cost_usd": results.get("usage", {}).get("estimated_cost_usd"),
                    "decision_id": results.get("decision_id"), "audit_recorded": results.get("audit_recorded")})
            except httpx.HTTPError as exc:
                rows.append({"i": i, "scenario": item["scenario"], "transaction_id": item["event"]["transaction_id"], "status": 0,
                             "error": type(exc).__name__, "wall_ms": round((time.perf_counter() - started) * 1000, 1)})
            if (i + 1) % 20 == 0:
                print(f"  sent {i + 1}/{n}")
    return rows


def save(label: str, rows: list[dict], meta: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{label}.json").write_text(json.dumps({"meta": meta, "rows": rows}, indent=1), encoding="utf8")
    fields = sorted({k for r in rows for k in r}, key=lambda k: ["i", "scenario", "transaction_id", "status"].index(k) if k in ("i", "scenario", "transaction_id", "status") else 99)
    with (OUT_DIR / f"{label}.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--spawn", action="store_true", help="start a local uvicorn server (isolated audit db) for the run")
    args = parser.parse_args()

    server = None
    base_url = args.base_url
    if args.spawn:
        port = 8765
        base_url = f"http://127.0.0.1:{port}"
        env = {**os.environ, "AUDIT_DB_PATH": str(OUT_DIR / f"{args.label}_audit.db"), "PYTHONUNBUFFERED": "1"}
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port), "--log-level", "warning"],
                                  cwd=str(Path(__file__).resolve().parent.parent), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        started = time.time()
        rows = run(base_url, args.n, args.seed)
        meta = {"label": args.label, "n": args.n, "seed": args.seed, "base_url": base_url, "duration_s": round(time.time() - started, 1)}
        save(args.label, rows, meta)
        print(f"done: {len(rows)} events in {meta['duration_s']} s -> data/simulation/{args.label}.json")
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
