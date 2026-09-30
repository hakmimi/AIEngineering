"""Offline tests for the Day 15 LangGraph RAG workflow."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import graph
from errors import ExternalServiceError
from main import app

CHUNK = {"doc_id": 1, "chunk_id": 0, "topic": "Masada", "text": "Masada is a fortress.", "score": 0.9, "similarity": 0.9}


@pytest.fixture
def fakes(monkeypatch):
    seen = {"retrieval": [], "prompts": []}
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda q, k, f=None, wide=False: seen["retrieval"].append((q, k)) or [CHUNK])
    monkeypatch.setattr(graph, "get_answer", lambda p: seen["prompts"].append(p) or
                        {"answer": "A fortress [1:0].", "confidence": 0.9, "score": None})
    return seen


def test_happy_path_runs_all_three_nodes_in_order(fakes):
    r = graph.run_graph("Where is Masada?", 3)
    assert r["graph"]["trace"] == ["receive_query", "input_guard", "route_query", "retrieve_context", "call_llm", "output_guard"]
    assert r["source"] == "rag" and r["answer"].startswith("A fortress") and r["confidence"] == 0.9
    assert fakes["retrieval"] == [("Where is Masada?", 3)]  # simple route caps top_k at 3


def test_receive_node_normalises_whitespace(fakes):
    graph.run_graph("  Where   is \n Masada?  ")
    assert fakes["retrieval"][0][0] == "Where is Masada?"


def test_state_accumulates_via_reducers(fakes):
    r = graph.run_graph("Where is Masada?")
    assert set(r["timings"]) == {"receive_query", "input_guard", "route_query", "retrieve_context", "call_llm", "output_guard", "total_ms"}   # merged, not overwritten
    assert len(r["graph"]["trace"]) == 6                                                       # appended, not overwritten


def test_blank_question_short_circuits_via_conditional_edge(fakes):
    r = graph.run_graph("   ")
    assert r["source"] == "invalid_input" and r["graph"]["trace"] == ["receive_query"]
    assert fakes["retrieval"] == [] and fakes["prompts"] == []


def test_weak_context_skips_the_llm_node_work(monkeypatch):
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda q, k, f=None, wide=False: [])
    monkeypatch.setattr(graph, "get_answer", lambda p: pytest.fail("LLM called with no context"))
    r = graph.run_graph("What is the capital of France?")
    assert r["source"] == "no_context" and r["graph"]["trace"][-2:] == ["call_llm", "output_guard"]


def test_llm_failure_becomes_fallback_answer(monkeypatch):
    def boom(prompt):
        raise ExternalServiceError()

    monkeypatch.setattr(graph, "get_relevant_chunks", lambda q, k, f=None, wide=False: [CHUNK])
    monkeypatch.setattr(graph, "get_answer", boom)
    assert graph.run_graph("Where is Masada?")["source"] == "fallback_error"


def test_graph_structure():
    g = graph.rag_graph.get_graph()
    assert {"receive_query", "route_query", "direct_answer", "fallback_response", "retrieve_context", "call_llm"} <= set(g.nodes)
    edges = {(e.source, e.target) for e in g.edges}
    assert ("retrieve_context", "call_llm") in edges and ("__start__", "receive_query") in edges and ("route_query", "direct_answer") in edges


def test_endpoint_returns_graph_trace(fakes):
    r = TestClient(app).post("/rag/graph", json={"query": "Where is Masada?", "top_k": 2})
    body = r.json()["results"]
    assert r.status_code == 200 and body["route"] == "rag" and body["graph"]["trace"][0] == "receive_query"
    assert TestClient(app).post("/rag/graph", json={"query": ""}).status_code == 422


# --- Day 16: conditional routing ------------------------------------------------------------------
import intent
from intent import DIRECT, FALLBACK, RAG


def test_smalltalk_takes_direct_path_without_any_api_call(monkeypatch):
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: pytest.fail("retrieval called"))
    monkeypatch.setattr(graph, "get_answer", lambda p: pytest.fail("LLM called"))
    r = graph.run_graph("hello")
    assert r["route"] == DIRECT and r["source"] == "direct"
    assert r["graph"]["trace"] == ["receive_query", "input_guard", "route_query", "direct_answer"]
    assert r["graph"]["route_reason"] == "smalltalk" and r["graph"]["routed_by"] == "rule"


def test_unclear_query_takes_fallback_path(monkeypatch):
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: pytest.fail("retrieval called"))
    r = graph.run_graph("Jerusalem")
    assert r["route"] == FALLBACK and r["source"] == "fallback" and "rephrase" in r["answer"]
    assert r["graph"]["trace"][-1] == "fallback_response"


def test_complex_query_widens_retrieval(monkeypatch):
    seen = []
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda q, k, f=None, wide=False: seen.append((k, wide)) or [CHUNK])
    monkeypatch.setattr(graph, "get_answer", lambda p: {"answer": "ok", "confidence": 0.9, "score": None})
    r = graph.run_graph("Compare Tel Aviv and Haifa", 2)
    assert seen == [(6, True)] and r["graph"]["query_type"] == "complex"


def test_simple_query_caps_top_k(monkeypatch):
    seen = []
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda q, k, f=None, wide=False: seen.append((k, wide)) or [CHUNK])
    monkeypatch.setattr(graph, "get_answer", lambda p: {"answer": "ok", "confidence": 0.9, "score": None})
    graph.run_graph("Where is Masada?", 9)
    assert seen == [(3, False)]


def test_llm_router_mode_decides_and_is_recorded(monkeypatch):
    monkeypatch.setattr(intent, "settings", type("S", (), {"llm_routing": True})())
    monkeypatch.setattr(intent, "get_structured", lambda p, s, n: {"route": "rag", "query_type": "complex", "reason": "multi-part"})
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda q, k, f=None, wide=False: [CHUNK])
    monkeypatch.setattr(graph, "get_answer", lambda p: {"answer": "ok", "confidence": 0.9, "score": None})
    r = graph.run_graph("Tell me about the Galilee")
    assert r["graph"]["routed_by"] == "llm" and r["graph"]["query_type"] == "complex"


def test_llm_router_failure_falls_back_to_rules(monkeypatch):
    def boom(*a):
        raise ExternalServiceError()

    monkeypatch.setattr(intent, "get_structured", boom)
    d = intent.llm_classify("hello")
    assert (d.route, d.by) == (DIRECT, "rule")


def test_llm_classifier_maps_direct_and_fallback_to_canned_answers(monkeypatch):
    monkeypatch.setattr(intent, "get_structured", lambda p, s, n: {"route": "fallback", "query_type": "simple", "reason": "vague"})
    d = intent.llm_classify("ok")
    assert d.route == FALLBACK and d.answer == intent.FALLBACK_ANSWER


def test_rule_classifier_table():
    table = {"hello": DIRECT, "Jerusalem": FALLBACK, "Where is Masada?": RAG}
    assert {q: intent.rule_classify(q).route for q in table} == table
    assert intent.rule_classify("Compare Tel Aviv and Haifa").query_type == "complex"
    assert intent.rule_classify("How do visitors reach Masada?").query_type == "simple"
