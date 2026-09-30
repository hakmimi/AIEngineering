"""Offline tests for Day 23: structured logs, request ids, per-node/tool/retrieval events."""
import io
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import graph
import observability
import tools
from main import app
from observability import JsonFormatter, configure_logging, log_event, redact, request_id_var, summarize

CHUNK = {"doc_id": 1, "chunk_id": 0, "topic": "Masada", "text": "Masada is a fortress.", "score": 0.9, "similarity": 0.9}


@pytest.fixture
def logs():
    """Capture the app's structured log lines (parsed JSON) for the duration of a test."""
    buf = io.StringIO()
    configure_logging(stream=buf, fmt="json")
    yield lambda: [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    configure_logging()


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: [CHUNK])
    monkeypatch.setattr(graph, "get_answer", lambda p: {"answer": "A fortress.", "confidence": 0.9, "score": None})


# --- building blocks --------------------------------------------------------------------------------
def test_log_event_emits_text_and_structured_fields(logs):
    token = request_id_var.set("req123")
    log_event(logging.getLogger("t"), "thing_happened", count=3, name="x")
    request_id_var.reset(token)
    (line,) = logs()
    assert line["event"] == "thing_happened" and line["count"] == 3 and line["name"] == "x"
    assert line["request_id"] == "req123" and line["level"] == "INFO" and line["ts"].endswith("+00:00")


def test_legacy_free_text_lines_still_parse(logs):
    logging.getLogger("t").warning("old_style key=value more text")
    (line,) = logs()
    assert line["event"] == "old_style" and line["msg"] == "old_style key=value more text"


def test_exceptions_are_included(logs):
    try:
        1 / 0
    except ZeroDivisionError:
        logging.getLogger("t").exception("boom")
    assert "ZeroDivisionError" in logs()[0]["exception"]


def test_redaction_and_summaries(monkeypatch):
    monkeypatch.delenv("LOG_USER_TEXT", raising=False)
    assert redact("secret question") == "<15 chars>" and redact(None) == "-"
    monkeypatch.setenv("LOG_USER_TEXT", "1")
    assert redact("secret question") == "secret question"
    assert summarize("x" * 200, 10) == "xxxxxxxxxx...(+190)" and summarize({"a": 1}) == '{"a": 1}'


def test_configure_logging_is_idempotent(logs):
    configure_logging(stream=io.StringIO())
    configure_logging(stream=io.StringIO())
    ours = [h for h in logging.getLogger().handlers if getattr(h, "_app_handler", False)]
    assert len(ours) == 1


def test_text_format_is_readable():
    buf = io.StringIO()
    configure_logging(stream=buf, fmt="text")
    token = request_id_var.set("abc")
    log_event(logging.getLogger("t"), "hello", a=1)
    request_id_var.reset(token)
    configure_logging()
    assert "[abc]" in buf.getvalue() and "hello a=1" in buf.getvalue()


# --- request id ----------------------------------------------------------------------------------------
def test_request_id_generated_and_returned():
    r = TestClient(app).get("/health")
    assert len(r.headers["X-Request-ID"]) == 12 and float(r.headers["X-Process-Time-Ms"]) >= 0


def test_incoming_request_id_is_honoured():
    assert TestClient(app).get("/health", headers={"X-Request-ID": "trace-me-1"}).headers["X-Request-ID"] == "trace-me-1"


def test_two_requests_get_different_ids():
    c = TestClient(app)
    assert c.get("/health").headers["X-Request-ID"] != c.get("/health").headers["X-Request-ID"]


def test_start_and_end_logged_with_latency(logs):
    TestClient(app).get("/health", headers={"X-Request-ID": "rid1"})
    events = [(l["event"], l) for l in logs() if l["request_id"] == "rid1"]
    assert [e for e, _ in events] == ["request_start", "request_end"]
    end = events[-1][1]
    assert end["status"] == 200 and end["path"] == "/health" and end["latency_ms"] >= 0


def test_every_line_of_a_request_shares_its_id_and_reconstructs_the_flow(logs, fakes):
    TestClient(app).post("/rag/graph", json={"query": "Where is Masada?"}, headers={"X-Request-ID": "rid2"})
    lines = [l for l in logs() if l["request_id"] == "rid2"]
    events = [l["event"] for l in lines]
    assert events[0] == "request_start" and events[-1] == "request_end"
    for expected in ("graph_route", "graph_node", "graph_done"):
        assert expected in events
    nodes = [l["node"] for l in lines if l["event"] == "graph_node"]
    assert nodes == ["receive_query", "input_guard", "route_query", "retrieve_context", "call_llm", "output_guard"]
    assert all(l["ms"] >= 0 for l in lines if l["event"] == "graph_node")           # per-node latency
    route = next(l for l in lines if l["event"] == "graph_route")
    assert (route["route"], route["query_type"], route["routed_by"]) == ("rag", "simple", "rule")   # routing decision
    done = next(l for l in lines if l["event"] == "graph_done")
    assert done["trace"] == nodes and "total_ms" in done["timings"]


def test_no_user_text_in_logs_by_default(logs, fakes, monkeypatch):
    monkeypatch.delenv("LOG_USER_TEXT", raising=False)
    TestClient(app).post("/rag/graph", json={"query": "Where is Masada?"})
    assert "Masada?" not in "".join(json.dumps(l) for l in logs())


def test_errors_are_logged_with_request_id_and_returned_to_client(logs, monkeypatch):
    import routes
    monkeypatch.setattr(routes, "run_graph", lambda *a, **k: 1 / 0)
    r = TestClient(app, raise_server_exceptions=False).post("/rag/graph", json={"query": "hi there"}, headers={"X-Request-ID": "rid3"})
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error", "request_id": "rid3"}
    err = [l for l in logs() if l["request_id"] == "rid3" and l["level"] == "ERROR"]
    assert any("ZeroDivisionError" in l.get("exception", "") for l in err)


def test_app_errors_include_request_id(logs):
    r = TestClient(app).post("/chat", json={"session_id": "ok", "query": "hello"}, headers={"X-Request-ID": "rid4"})
    assert r.status_code == 200
    r = TestClient(app).get("/session/bad id!", headers={"X-Request-ID": "rid4"})
    assert r.status_code in (404, 422)


# --- domain events ---------------------------------------------------------------------------------------
def test_tool_calls_are_logged_with_args_and_output_summary(logs):
    tools.execute_tool("calculate", {"expression": "6*7"})
    line = next(l for l in logs() if l["event"] == "tool_call")
    assert line["tool"] == "calculate" and line["args"] == {"expression": "6*7"} and line["ok"] is True
    assert line["output"] == "42.0" and line["ms"] >= 0


def test_failed_tool_call_is_logged(logs):
    tools.execute_tool("calculate", {"expression": "1/0"})
    line = next(l for l in logs() if l["event"] == "tool_call")
    assert line["ok"] is False and "division" in line["error"]


def test_node_failure_logged_with_context(logs, monkeypatch):
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: 1 / 0)
    graph.run_graph("Where is Masada?")
    line = next(l for l in logs() if l["event"] == "graph_node_failed")
    assert line["node"] == "retrieve_context" and line["error_type"] == "ZeroDivisionError"
    assert line["route"] == "rag" and line["question_len"] == 16 and line["level"] == "ERROR"


def test_retrieval_event_lists_chunk_metadata(logs, monkeypatch):
    import retrieval
    from vector_store import VectorStore
    chunks = [{"doc_id": 1, "chunk_id": 0, "topic": "Masada", "category": "history", "text": "fortress", "embedded_text": [1.0, 0.0, 0.0]}]
    monkeypatch.setattr(retrieval, "get_embedding", lambda q: [1.0, 0.0, 0.0])
    monkeypatch.setattr(retrieval, "get_store", lambda: VectorStore.build(chunks))
    retrieval.get_relevant_chunks("masada fortress", 2)
    line = next(l for l in logs() if l["event"] == "retrieval")
    assert line["kept"] == 1 and line["chunks"][0]["topic"] == "Masada" and line["chunks"][0]["expanded"] is False
    assert line["embed_ms"] >= 0 and line["search_ms"] >= 0 and line["query_len"] == 15


def test_json_formatter_never_raises_on_odd_values():
    record = logging.LogRecord("x", logging.INFO, "", 0, "msg", (), None)
    record.fields = {"obj": object(), "set": {1, 2}}
    record.event = "odd"
    assert json.loads(JsonFormatter().format(record))["event"] == "odd"


def test_module_exports():
    assert observability.new_request_id() != observability.new_request_id()
