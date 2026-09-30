"""Offline tests for Day 17: tools as graph nodes, validated inputs/outputs."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import graph
import intent
import tools
from errors import ExternalServiceError
from main import app
from tool_agent import ToolDecision
from tools import execute_tool

ANSWER = {"answer": "It is 84.", "confidence": 0.9, "score": None}


# --- calculate_score + output contracts --------------------------------------------------------
def test_calculate_score_weighted_and_default_weights():
    assert execute_tool("calculate_score", {"values": [80, 90, 100], "weights": [1, 1, 2]}).output == 92.5
    assert execute_tool("calculate_score", {"values": [10, 20]}).output == 15


@pytest.mark.parametrize("args,fragment", [
    ({"values": [1], "weights": [1, 2]}, "same length"),
    ({"values": [1, 2], "weights": [0, 0]}, "not all zero"),
    ({"values": [1, 2], "weights": [-1, 2]}, "non-negative"),
    ({"values": []}, "invalid arguments"),
    ({}, "invalid arguments"),
])
def test_calculate_score_invalid_inputs(args, fragment):
    r = execute_tool("calculate_score", args)
    assert not r.ok and fragment in r.error


def test_output_validation_blocks_bad_tool_results(monkeypatch):
    bad = tools.Tool("calculate", "x", tools.CalculateInput, lambda a: float("nan"), tools._check_number)
    monkeypatch.setitem(tools.TOOLS, "calculate", bad)
    r = execute_tool("calculate", {"expression": "1+1"})
    assert not r.ok and "non-finite" in r.error


def test_search_hits_contract():
    with pytest.raises(ValueError):
        tools._check_hits([{"topic": "x"}])
    tools._check_hits([{"topic": "x", "text": "y", "score": 1}])


# --- routing into the tool branch -------------------------------------------------------------------
@pytest.mark.parametrize("q", ["12*(3+4)", "List the nature topics"])
def test_rules_route_obvious_tool_requests(q):
    d = intent.rule_classify(q)
    assert d.route == intent.TOOL and d.reason.startswith("rule:") and d.by == "rule"


def test_knowledge_questions_still_route_to_rag():
    assert intent.rule_classify("Where is Masada?").route == intent.RAG


# --- graph paths --------------------------------------------------------------------------------------
@pytest.fixture
def llm(monkeypatch):
    calls = []
    monkeypatch.setattr(graph, "get_answer", lambda p: calls.append(p) or ANSWER)
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: pytest.fail("retrieval called on the tool path"))
    return calls


def test_calculate_path_trace_and_result(llm):
    r = graph.run_graph("12*(3+4)")
    assert r["graph"]["trace"] == ["receive_query", "input_guard", "route_query", "select_tool", "run_tool", "tool_answer", "output_guard"]
    assert r["tool"]["name"] == "calculate" and r["tool"]["output"] == 84.0 and r["tool"]["ok"] and r["source"] == "tool"
    assert "84.0" in llm[0] and "Tool result" in llm[0]          # the prompt carries the tool result


def test_rule_selected_tool_makes_no_selection_llm_call(monkeypatch, llm):
    monkeypatch.setattr(graph, "llm_decision", lambda q: pytest.fail("LLM tool selection called"))
    assert graph.run_graph("12*(3+4)")["tool"]["decided_by"] == "rule"


def test_tool_error_is_reported_through_the_graph(llm, monkeypatch):
    monkeypatch.setattr(graph, "get_answer", lambda p: llm.append(p) or
                        {"answer": "Division by zero is undefined.", "confidence": 0.9, "score": None})
    r = graph.run_graph("10/0")
    assert r["source"] == "tool_error" and r["tool"]["ok"] is False and "division" in r["tool"]["error"]
    assert "ERROR" in llm[0]


def test_llm_down_on_tool_path_still_returns_the_tool_result(monkeypatch):
    def boom(p):
        raise ExternalServiceError()

    monkeypatch.setattr(graph, "get_answer", boom)
    assert graph.run_graph("6*7")["answer"] == "42.0"


def test_selected_search_docs_continues_on_the_retrieval_path(monkeypatch):
    chunk = {"doc_id": 1, "chunk_id": 0, "topic": "Masada", "text": "t", "score": 0.9, "similarity": 0.9}
    monkeypatch.setattr(graph, "rule_decision", lambda q: None)
    monkeypatch.setattr(graph, "llm_decision", lambda q: ToolDecision("search_docs", {"query": q}, "llm"))
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: [chunk])
    monkeypatch.setattr(graph, "get_answer", lambda p: {"answer": "fortress", "confidence": 0.9, "score": None})
    # drive select_tool -> retrieve directly through the conditional edge helper
    assert graph._after_select({"tool_name": "search_docs"}) == "retrieve_context"
    assert graph._after_select({"tool_name": "none"}) == "retrieve_context"
    assert graph._after_select({"tool_name": "calculate"}) == "run_tool"


def test_llm_router_can_choose_the_tool_route(monkeypatch, llm):
    monkeypatch.setattr(intent, "settings", type("S", (), {"llm_routing": True})())
    monkeypatch.setattr(intent, "get_structured", lambda p, s, n: {"route": "tool", "query_type": "simple", "reason": "percentage"})
    monkeypatch.setattr(graph, "rule_decision", lambda q: None)
    monkeypatch.setattr(graph, "llm_decision", lambda q: ToolDecision("calculate", {"expression": "0.15*240"}, "llm"))
    r = graph.run_graph("What is 15% of 240?")
    assert r["route"] == "tool" and r["tool"]["output"] == 36.0 and r["tool"]["decided_by"] == "llm"


def test_graph_structure_has_tool_branch():
    g = graph.rag_graph.get_graph()
    assert {"select_tool", "run_tool", "tool_answer"} <= set(g.nodes)
    edges = {(e.source, e.target) for e in g.edges}
    assert {("route_query", "select_tool"), ("run_tool", "tool_answer"), ("select_tool", "retrieve_context")} <= edges


def test_endpoint_exposes_tool_call(llm):
    body = TestClient(app).post("/rag/graph", json={"query": "12*(3+4)"}).json()["results"]
    assert body["tool"]["output"] == 84.0 and body["route"] == "tool"
