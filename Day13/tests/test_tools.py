"""Offline tests for Day 11 tools + tool decision layer."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import tool_agent
import tools
from errors import ExternalServiceError
from main import app
from tools import execute_tool, safe_eval


# --- calculator ----------------------------------------------------------------------
@pytest.mark.parametrize("expr,expected", [("2+3*4", 14), ("(1+2)*3", 9), ("2^3", 8), ("10/4", 2.5),
                                           ("-5+2", -3), ("1,000*2", 2000), ("7%3", 1)])
def test_safe_eval_values(expr, expected):
    assert safe_eval(expr) == expected


@pytest.mark.parametrize("expr", ["__import__('os').system('echo hi')", "open('x')", "a+1", "2**1000", "1/0",
                                  "2+", "True+1", "[1,2]", "(lambda: 1)()"])
def test_safe_eval_rejects_unsafe_or_invalid(expr):
    with pytest.raises(ValueError):
        safe_eval(expr)


# --- executor --------------------------------------------------------------------------
def test_execute_tool_success_and_error_paths():
    assert execute_tool("calculate", {"expression": "6*7"}).output == 42
    bad = execute_tool("calculate", {"expression": "1/0"})
    assert not bad.ok and "division" in bad.error
    assert not execute_tool("calculate", {}).ok              # missing argument -> validation error
    assert not execute_tool("nope", {}).ok                   # unknown tool
    assert not execute_tool("list_topics", {"category": "spaceships"}).ok


def test_list_topics_by_category():
    result = execute_tool("list_topics", {"category": "History"})
    assert result.ok and "Masada" in result.output and "Jerusalem" not in result.output
    assert len(execute_tool("list_topics", {}).output) == 53


def test_search_docs_tool_shapes_output(monkeypatch):
    monkeypatch.setattr(tools, "get_relevant_chunks",
                        lambda q, k: [{"topic": "Masada", "text": "fortress", "score": 0.91234}])
    assert execute_tool("search_docs", {"query": "masada"}).output == [{"topic": "Masada", "text": "fortress", "score": 0.912}]


# --- decision layer ----------------------------------------------------------------------
@pytest.mark.parametrize("q", ["12*(3+4)", "What is 7+8?", "calculate 100/4", "2^10"])
def test_rules_catch_pure_arithmetic(q):
    assert tool_agent.rule_decision(q).tool == "calculate"


@pytest.mark.parametrize("q", ["Where is Masada?", "What is 15% of 240?", "In 1948 Israel was founded", "Tell me about Eilat"])
def test_rules_do_not_catch_language(q):
    assert tool_agent.rule_decision(q) is None


def test_llm_decision_maps_arguments(monkeypatch):
    monkeypatch.setattr(tool_agent, "get_structured", lambda p, s, n: {
        "tool": "list_topics", "query": "", "expression": "", "category": "nature"})
    d = tool_agent.llm_decision("what nature topics exist")
    assert (d.tool, d.arguments, d.decided_by) == ("list_topics", {"category": "nature"}, "llm")


def test_llm_decision_failure_defaults_to_search(monkeypatch):
    def boom(*a):
        raise ExternalServiceError()

    monkeypatch.setattr(tool_agent, "get_structured", boom)
    d = tool_agent.llm_decision("anything")
    assert (d.tool, d.decided_by) == ("search_docs", "fallback")


def test_choice_schema_lists_every_tool():
    assert set(tool_agent.TOOL_CHOICE_SCHEMA["properties"]["tool"]["enum"]) == set(tools.TOOLS) | {"none"}


# --- end to end (mocked LLM) ---------------------------------------------------------------
def test_rule_path_makes_no_decision_llm_call(monkeypatch):
    monkeypatch.setattr(tool_agent, "get_structured", lambda *a: pytest.fail("decision LLM called"))
    monkeypatch.setattr(tool_agent, "get_answer", lambda p: {"answer": "It is 84.", "confidence": 0.9, "score": None})
    r = tool_agent.run_with_tools("12*(3+4)")
    assert r["tool"]["name"] == "calculate" and r["tool"]["decided_by"] == "rule" and r["tool"]["output"] == 84.0
    assert r["source"] == "tool"


def test_tool_error_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(tool_agent, "get_answer", lambda p: {"answer": "Cannot divide by zero.", "confidence": 0.9, "score": None})
    r = tool_agent.run_with_tools("10/0")
    assert r["source"] == "tool_error" and r["tool"]["ok"] is False


def test_answer_llm_down_still_returns_tool_result(monkeypatch):
    def boom(p):
        raise ExternalServiceError()

    monkeypatch.setattr(tool_agent, "get_answer", boom)
    assert tool_agent.run_with_tools("6*7")["answer"] == "42.0"


def test_knowledge_question_uses_rag(monkeypatch):
    monkeypatch.setattr(tool_agent, "get_structured", lambda p, s, n: {
        "tool": "search_docs", "query": "masada", "expression": "", "category": ""})
    monkeypatch.setattr(tool_agent, "get_rag_answer", lambda q, k: {"answer": "A fortress", "source": "rag"})
    r = tool_agent.run_with_tools("Where is Masada?")
    assert r["source"] == "rag" and r["tool"]["name"] == "search_docs"


def test_smalltalk_skips_tools(monkeypatch):
    monkeypatch.setattr(tool_agent, "decide", lambda q: pytest.fail("decision called"))
    assert tool_agent.run_with_tools("hello")["source"] == "smalltalk"


def test_endpoint(monkeypatch):
    monkeypatch.setattr(tool_agent, "get_answer", lambda p: {"answer": "It is 42.", "confidence": 0.9, "score": None})
    resp = TestClient(app).post("/ask/tools", json={"query": "6*7"})
    assert resp.status_code == 200 and resp.json()["results"]["tool"]["output"] == 42.0
