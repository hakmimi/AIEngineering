"""Send 5 live requests through the real app, capture the JSON logs, and reconstruct each request from its id.

    python -m scripts.log_demo        -> data/logs/sample_requests.jsonl + a per-request summary
"""
import json
import tempfile
from collections import defaultdict
from pathlib import Path

from fastapi.testclient import TestClient

import chat
import memory as memory_module
import routes
from config import settings
from main import app
from observability import configure_logging

memory_module.memory = memory_module.SqliteMemoryStore(Path(tempfile.mkdtemp()) / "demo.db")
routes.memory = chat.memory = memory_module.memory
out_dir = settings.base_dir / "data" / "logs"
out_dir.mkdir(parents=True, exist_ok=True)
log_path = out_dir / "sample_requests.jsonl"
log_file = log_path.open("w", encoding="utf8")
configure_logging(stream=log_file, fmt="json")   # after importing main, which configures stdout logging itself

client = TestClient(app)
for i, query in enumerate(["hello", "Where is Masada?", "Compare Tel Aviv and Haifa", "12*(3+4)", "What is the capital of France?"], 1):
    client.post("/rag/graph", json={"query": query}, headers={"X-Request-ID": f"demo-{i}"})
log_file.close()

by_request = defaultdict(list)
for line in log_path.read_text(encoding="utf8").splitlines():
    record = json.loads(line)
    by_request[record["request_id"]].append(record)

print(f"{len(by_request)} requests, {sum(map(len, by_request.values()))} log lines -> {log_path}\n")
for rid, lines in by_request.items():
    if not rid.startswith("demo-"):
        continue
    end = next(rec for rec in lines if rec["event"] == "request_end")
    route = next(rec for rec in lines if rec["event"] == "graph_route")
    nodes = [(rec["node"], rec["ms"]) for rec in lines if rec["event"] == "graph_node"]
    slowest = max(nodes, key=lambda n: n[1])
    print(f"{rid}: route={route['route']}/{route['query_type']} status={end['status']} latency={end['latency_ms']}ms "
          f"lines={len(lines)} slowest={slowest[0]} ({slowest[1]}ms)\n    nodes: " + " -> ".join(f"{n} {ms}ms" for n, ms in nodes))
