"""Fresh-checkout test: does the project run from nothing but its files and requirements.txt?

    python -m scripts.fresh_run [--no-tests]

Copies the project (without .env, databases, caches) into a temp folder, builds a NEW virtual environment, installs requirements-dev.txt,
runs the test suite, starts the real server WITHOUT an OpenAI key, and makes real HTTP calls: /health, /ready, a rules-only decision and its audit record.
It proves the dependency list and the shipped data are complete; it does not prove the Docker image (see README).
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path

import httpx

SRC = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns(".env", ".env.*", "__pycache__", ".pytest_cache", ".ruff_cache", ".coverage", ".venv", "audit.db", "jobs.db")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(run_tests: bool) -> int:
    work = Path(tempfile.mkdtemp(prefix="fresh_run_"))
    app = work / "app"
    shutil.copytree(SRC, app, ignore=IGNORE)
    shutil.copy(SRC / ".env.example", app / ".env.example")
    print(f"copy: {app}")
    venv.create(work / "venv", with_pip=True)
    py = work / "venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "APP_API_KEY", "PYTHONPATH")}
    started = time.perf_counter()
    subprocess.run([py, "-m", "pip", "install", "-q", "-r", "requirements-dev.txt"], cwd=app, env=env, check=True)
    print(f"pip install: {time.perf_counter() - started:.0f} s")
    if run_tests:
        res = subprocess.run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=app, env=env, capture_output=True, text=True)
        print("tests:", res.stdout.strip().splitlines()[-1] if res.stdout.strip() else res.stderr[-300:])
        if res.returncode:
            print(res.stdout[-2000:])
            return 1
    port = free_port()
    server = subprocess.Popen([py, "-m", "uvicorn", "main:app", "--port", str(port)], cwd=app, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            print("server did not start:\n", server.stdout.read() if server.poll() is not None else "(still starting)")
            return 1
        ready = httpx.get(f"{base}/ready").json()
        print("ready:", ready["status"], ready["checks"])
        tx = {"transaction_id": "fresh-1", "timestamp": "2026-01-05T09:12:00Z", "amount": 80.0, "currency": "USD", "country": "KP",
              "merchant_category": "electronics", "customer_type": "returning", "payment_method": "card", "customer_age_days": 300}
        body = httpx.post(f"{base}/decision", json=tx, timeout=30).json()
        audit = httpx.get(f"{base}/decision/audit/{body['decision_id']}").json()
        print("decision:", body["decision"]["action"], body["decision"]["reason_codes"], "| audit integrity:", audit["integrity_ok"])
        ok = ready["status"] == "ready" and body["decision"]["action"] == "decline" and audit["integrity_ok"]
        print("FRESH RUN", "PASSED" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        server.terminate()
        server.wait(10)
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-tests", action="store_true")
    sys.exit(main(not parser.parse_args().no_tests))
