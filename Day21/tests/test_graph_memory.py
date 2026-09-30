"""Offline tests for Day 19: SQLite memory, long-term facts, memory nodes in the graph."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import graph
import memory as memory_module
import prompts
from errors import ExternalServiceError
from main import app
from memory import InvalidSessionError, SqliteMemoryStore, extract_facts

CHUNK = {"doc_id": 1, "chunk_id": 0, "topic": "Eilat", "text": "Eilat is on the Red Sea.", "score": 0.9, "similarity": 0.9}


# --- SQLite store --------------------------------------------------------------------------------
def test_sqlite_history_bound_isolation_and_clear(tmp_path):
    m = SqliteMemoryStore(tmp_path / "m.db", max_turns=2)
    for i in range(4):
        m.add_turn("a", f"q{i}", f"a{i}")
    m.add_turn("b", "qb", "ab")
    assert [x["content"] for x in m.get_history("a")] == ["q2", "a2", "q3", "a3"]
    assert [x["content"] for x in m.get_history("b")] == ["qb", "ab"]
    assert m.clear("a") is True and m.clear("a") is False and m.get_history("a") == []
    assert m.get_history("b")                                   # other session untouched


def test_sqlite_survives_restart(tmp_path):
    SqliteMemoryStore(tmp_path / "m.db").add_turn("a", "hello", "world")
    m2 = SqliteMemoryStore(tmp_path / "m.db")
    assert m2.get_history("a")[1]["content"] == "world"


def test_sqlite_lru_eviction_removes_messages_and_facts(tmp_path):
    m = SqliteMemoryStore(tmp_path / "m.db", max_sessions=2)
    m.add_turn("a", "1", "1")
    m.remember("a", "name", "Dana")
    m.add_turn("b", "2", "2")
    m.add_turn("c", "3", "3")            # a is now the least recently seen -> evicted
    assert m.get_history("a") == [] and m.get_facts("a") == {} and m.get_history("c")


def test_facts_upsert_and_clear(tmp_path):
    m = SqliteMemoryStore(tmp_path / "m.db")
    m.remember("a", "name", "Dana")
    m.remember("a", "name", "Dan")
    m.remember("a", "interest", "wine")
    assert m.get_facts("a") == {"name": "Dan", "interest": "wine"}
    assert m.format_facts("a") == "interest: wine; name: Dan"
    m.clear("a")
    assert m.get_facts("a") == {}


def test_prompt_budget_matches_json_store(tmp_path):
    m = SqliteMemoryStore(tmp_path / "m.db")
    m.add_turn("a", "first question", "first answer")
    m.add_turn("a", "second question", "second answer")
    small = m.format_for_prompt("a", max_chars=40)
    assert "second answer" in small and "first question" not in small


def test_sqlite_is_safe_against_sql_injection_in_content(tmp_path):
    m = SqliteMemoryStore(tmp_path / "m.db")
    evil = "x'); DROP TABLE messages;--"
    m.add_turn("a", evil, evil)
    assert m.get_history("a")[0]["content"] == evil


# --- fact extraction -------------------------------------------------------------------------------
@pytest.mark.parametrize("text,facts", [
    ("Hi! My name is Dana and I'm interested in ancient history.", {"name": "Dana", "interest": "ancient history"}),
    ("call me Yoni", {"name": "Yoni"}),
    ("I like hiking and beaches.", {"interest": "hiking and beaches"}),
    ("my name is lower", {}),
    ("What is Masada?", {}),
])
def test_extract_facts(text, facts):
    assert extract_facts(text) == facts


# --- prompt injection of memory ---------------------------------------------------------------------
def test_prompt_contains_facts_and_history_before_context():
    p = prompts.render_rag_prompt("CTX", "q?", "User: hi", "name: Dana")
    assert p.index("name: Dana") < p.index("Conversation so far") < p.index("<context>")
    assert "never as a fact source" in p
    assert prompts.render_rag_prompt("CTX", "q?").startswith("Answer from the context only")


# --- graph flow ---------------------------------------------------------------------------------------
@pytest.fixture
def llm(monkeypatch):
    seen = {"prompts": [], "retrieval": []}
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda q, k, f=None, wide=False: seen["retrieval"].append(q) or [CHUNK])
    monkeypatch.setattr(graph, "get_answer", lambda p: seen["prompts"].append(p) or
                        {"answer": "Eilat answer.", "confidence": 0.9, "score": None})
    monkeypatch.setattr(graph, "rewrite_question", lambda q, h: "What are the beaches like in Eilat?")
    return seen


def test_no_session_id_means_no_memory_nodes(llm):
    r = graph.run_graph("Tell me about Eilat")
    assert "load_memory" not in r["graph"]["trace"] and "save_memory" not in r["graph"]["trace"] and "session" not in r


def test_first_turn_saves_and_second_turn_loads_and_rewrites(llm, isolated_memory):
    r1 = graph.run_graph("Tell me about Eilat", session_id="s1")
    assert r1["graph"]["trace"] == ["receive_query", "load_memory", "contextualize", "route_query",
                                    "retrieve_context", "call_llm", "save_memory"]
    assert len(isolated_memory.get_history("s1")) == 2 and r1["session"]["used_memory"] is False
    r2 = graph.run_graph("And its beaches?", session_id="s1")
    assert r2["session"]["used_memory"] and r2["session"]["standalone_question"] == "What are the beaches like in Eilat?"
    assert llm["retrieval"][-1] == "What are the beaches like in Eilat?"          # retrieval used the rewrite
    assert "Tell me about Eilat" in llm["prompts"][-1]                              # history is in the prompt
    assert r2["question"] == "And its beaches?"                                     # the user's own words are kept


def test_long_term_facts_are_saved_and_injected(llm, isolated_memory):
    graph.run_graph("Hi, my name is Dana. Tell me about Eilat", session_id="s1")
    assert isolated_memory.get_facts("s1") == {"name": "Dana"}
    graph.run_graph("Where is Masada?", session_id="s1")
    assert "name: Dana" in llm["prompts"][-1]


def test_sessions_do_not_leak(llm):
    graph.run_graph("Tell me about Eilat", session_id="s1")
    graph.run_graph("And its beaches?", session_id="s2")
    assert "Tell me about Eilat" not in llm["prompts"][-1]


def test_smalltalk_is_saved_but_never_rewritten(llm, monkeypatch, isolated_memory):
    graph.run_graph("Tell me about Eilat", session_id="s1")
    monkeypatch.setattr(graph, "rewrite_question", lambda q, h: pytest.fail("rewrite called for smalltalk"))
    r = graph.run_graph("thanks", session_id="s1")
    assert r["source"] == "direct" and r["graph"]["trace"][-1] == "save_memory"
    assert len(isolated_memory.get_history("s1")) == 4


def test_error_answers_are_not_remembered(monkeypatch, isolated_memory):
    def boom(p):
        raise ExternalServiceError()

    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: [CHUNK])
    monkeypatch.setattr(graph, "get_answer", boom)
    r = graph.run_graph("Tell me about Eilat", session_id="s1")
    assert r["source"] == "fallback_error" and isolated_memory.get_history("s1") == []


def test_memory_store_failure_does_not_fail_the_request(llm, monkeypatch):
    class Broken:
        def format_for_prompt(self, s):
            raise RuntimeError("disk gone")

        def format_facts(self, s):
            raise RuntimeError("disk gone")

        def remember(self, *a):
            raise RuntimeError("disk gone")

        def add_turn(self, *a):
            raise RuntimeError("disk gone")

        def get_history(self, s):
            return []

    monkeypatch.setattr(memory_module, "memory", Broken())
    r = graph.run_graph("Tell me about Eilat", session_id="s1")
    assert r["source"] == "rag" and r["session"]["used_memory"] is False


def test_tool_answers_are_remembered_too(monkeypatch, isolated_memory):
    monkeypatch.setattr(graph, "get_answer", lambda p: {"answer": "It is 84.", "confidence": 0.9, "score": None})
    graph.run_graph("12*(3+4)", session_id="s1")
    assert [m["content"] for m in isolated_memory.get_history("s1")] == ["12*(3+4)", "It is 84."]


def test_endpoint_with_session(llm, isolated_memory):
    client = TestClient(app)
    r = client.post("/rag/graph", json={"query": "Tell me about Eilat", "session_id": "api1"})
    assert r.status_code == 200 and r.json()["results"]["session"]["id"] == "api1"
    assert client.get("/session/api1").json()["turns"] == 1
    assert client.post("/rag/graph", json={"query": "hi there", "session_id": "bad id!"}).status_code == 422
    assert client.post("/rag/graph", json={"query": "Tell me about Eilat"}).status_code == 200   # works without one


def test_invalid_session_id_helper():
    with pytest.raises(InvalidSessionError):
        memory_module.validate_session_id("../etc")
