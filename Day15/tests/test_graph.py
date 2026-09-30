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
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda q, k: seen["retrieval"].append((q, k)) or [CHUNK])
    monkeypatch.setattr(graph, "get_answer", lambda p: seen["prompts"].append(p) or
                        {"answer": "A fortress [1:0].", "confidence": 0.9, "score": None})
    return seen


def test_happy_path_runs_all_three_nodes_in_order(fakes):
    r = graph.run_graph("Where is Masada?", 3)
    assert r["graph"]["trace"] == ["receive_query", "retrieve_context", "call_llm"]
    assert r["source"] == "rag" and r["answer"].startswith("A fortress") and r["confidence"] == 0.9
    assert fakes["retrieval"] == [("Where is Masada?", 3)]


def test_receive_node_normalises_whitespace(fakes):
    graph.run_graph("  Where   is \n Masada?  ")
    assert fakes["retrieval"][0][0] == "Where is Masada?"


def test_state_accumulates_via_reducers(fakes):
    r = graph.run_graph("Where is Masada?")
    assert set(r["timings"]) == {"receive_query", "retrieve_context", "call_llm", "total_ms"}   # merged, not overwritten
    assert len(r["graph"]["trace"]) == 3                                                       # appended, not overwritten


def test_blank_question_short_circuits_via_conditional_edge(fakes):
    r = graph.run_graph("   ")
    assert r["source"] == "invalid_input" and r["graph"]["trace"] == ["receive_query"]
    assert fakes["retrieval"] == [] and fakes["prompts"] == []


def test_weak_context_skips_the_llm_node_work(monkeypatch):
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda q, k: [])
    monkeypatch.setattr(graph, "get_answer", lambda p: pytest.fail("LLM called with no context"))
    r = graph.run_graph("What is the capital of France?")
    assert r["source"] == "no_context" and r["graph"]["trace"][-1] == "call_llm"


def test_llm_failure_becomes_fallback_answer(monkeypatch):
    def boom(prompt):
        raise ExternalServiceError()

    monkeypatch.setattr(graph, "get_relevant_chunks", lambda q, k: [CHUNK])
    monkeypatch.setattr(graph, "get_answer", boom)
    assert graph.run_graph("Where is Masada?")["source"] == "fallback_error"


def test_graph_structure():
    g = graph.rag_graph.get_graph()
    assert {"receive_query", "retrieve_context", "call_llm"} <= set(g.nodes)
    edges = {(e.source, e.target) for e in g.edges}
    assert ("retrieve_context", "call_llm") in edges and ("__start__", "receive_query") in edges


def test_endpoint_returns_graph_trace(fakes):
    r = TestClient(app).post("/rag/graph", json={"query": "Where is Masada?", "top_k": 2})
    body = r.json()["results"]
    assert r.status_code == 200 and body["route"] == "graph" and body["graph"]["trace"][0] == "receive_query"
    assert TestClient(app).post("/rag/graph", json={"query": ""}).status_code == 422
