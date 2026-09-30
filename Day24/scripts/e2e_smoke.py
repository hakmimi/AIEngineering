"""Live end-to-end smoke test through the real FastAPI app (real OpenAI, real FAISS, real SQLite memory in a temp dir).

    python -m scripts.e2e_smoke        exit code 0 = every scenario behaved as expected
"""
import logging
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

import memory as memory_module

memory_module.memory = memory_module.SqliteMemoryStore(Path(tempfile.mkdtemp()) / "smoke.db")   # never touch data/memory.db
import routes  # noqa: E402
import chat  # noqa: E402
import assistant  # noqa: E402
routes.memory = chat.memory = assistant.memory = memory_module.memory
from main import app  # noqa: E402

logging.disable(logging.CRITICAL)
client = TestClient(app)


def post(query: str, session: str | None = None, path: str = "/rag/graph") -> dict:
    body = {"query": query, **({"session_id": session} if session else {})}
    resp = client.post(path, json=body)
    assert resp.status_code == 200, (query, resp.status_code, resp.text)
    return resp.json()["results"]


SCENARIOS = [
    ("smalltalk costs nothing",       lambda: post("hello"),                       lambda r: r["source"] == "direct"),
    ("unclear input -> clarify",      lambda: post("ok"),                          lambda r: r["source"] == "fallback"),
    ("simple fact (rag)",             lambda: post("Where is Masada?"),            lambda r: r["source"] == "rag" and "Dead Sea" in r["answer"]),
    ("comparison (complex route)",    lambda: post("Compare Tel Aviv and Haifa"),  lambda r: r["graph"]["query_type"] == "complex" and "Haifa" in r["answer"]),
    ("out of domain -> refusal",      lambda: post("What is the capital of France?"), lambda r: r["source"] == "no_context"),
    ("calculator tool",               lambda: post("12*(3+4)"),                    lambda r: r["tool"]["output"] == 84.0),
    ("list tool",                     lambda: post("List the history topics"),     lambda r: "Masada" in r["tool"]["output"]),
    ("memory: turn 1",                lambda: post("Hi, my name is Dana. Tell me about Masada", "smoke"), lambda r: r["source"] == "rag"),
    ("memory: follow-up resolves 'it'", lambda: post("How do visitors reach it?", "smoke"),
     lambda r: "Masada" in r["session"]["standalone_question"] and "cable car" in r["answer"].lower()),
    ("memory: fact kept",             lambda: post("Where is Eilat?", "smoke"),    lambda r: r["session"]["user_facts"] == "name: Dana"),
    ("validation: empty query",       lambda: client.post("/rag/graph", json={"query": ""}).status_code, lambda r: r == 422),
    ("validation: bad session id",    lambda: client.post("/rag/graph", json={"query": "hi there", "session_id": "bad id!"}).status_code, lambda r: r == 422),
]

failures = 0
for name, call, check in SCENARIOS:
    try:
        ok = bool(check(call()))
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"      error: {exc}")
    failures += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
print(f"\n{len(SCENARIOS) - failures}/{len(SCENARIOS)} scenarios passed")
sys.exit(1 if failures else 0)
