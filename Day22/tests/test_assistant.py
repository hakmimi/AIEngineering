"""Offline end-to-end tests for the Day 14 complete assistant (LLM + retrieval mocked)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import assistant
import chat
import tool_agent
from main import app

CHUNK = {"doc_id": 1, "chunk_id": 0, "topic": "Eilat", "text": "Eilat is on the Red Sea.", "score": 0.9, "similarity": 0.9}


@pytest.fixture
def fakes(monkeypatch):
    calls = {"rag": [], "answer": 0, "structured": 0}
    monkeypatch.setattr(chat, "get_rag_answer", lambda q, k, f, h: calls["rag"].append((q, h)) or
                        {"answer": f"rag: {q}", "source": "rag", "retrieved_chunks": [CHUNK]})
    monkeypatch.setattr(chat, "get_structured", lambda p, s, n: calls.__setitem__("structured", calls["structured"] + 1) or
                        {"question": "What are the beaches like in Eilat?"})
    monkeypatch.setattr(tool_agent, "get_answer", lambda p: calls.__setitem__("answer", calls["answer"] + 1) or
                        {"answer": "tool answer", "confidence": 0.9, "score": None})
    return calls


@pytest.mark.parametrize("q,tool,args", [
    ("List the nature topics", "list_topics", {"category": "nature"}),
    ("what topics do you cover?", "list_topics", {"category": None}),
    ("Which places are in the history category", "list_topics", {"category": "history"}),
    ("2^10", "calculate", {"expression": "2^10"}),
])
def test_rules_pick_tools(q, tool, args):
    d = tool_agent.rule_decision(q)
    assert (d.tool, d.arguments, d.decided_by) == (tool, args, "rule")


@pytest.mark.parametrize("q", ["What is the history of Eilat?", "Where is Masada?", "Tell me about places to visit"])
def test_rules_leave_knowledge_questions_alone(q):
    assert tool_agent.rule_decision(q) is None


def test_tool_path_uses_no_decision_llm_and_saves_memory(fakes, isolated_memory):
    r = assistant.ask("u1", "List the history topics")
    assert r["tool"]["name"] == "list_topics" and r["tool"]["decided_by"] == "rule"
    assert "Masada" in r["tool"]["output"] and fakes["structured"] == 0
    assert len(isolated_memory.get_history("u1")) == 2


def test_knowledge_path_uses_memory_and_rewrite(fakes):
    assistant.ask("u1", "Tell me about Eilat")
    r = assistant.ask("u1", "And its beaches?")
    assert r["session"]["used_memory"] and fakes["rag"][1][0] == "What are the beaches like in Eilat?"


def test_mixed_conversation_shares_one_memory(fakes, isolated_memory):
    assistant.ask("u1", "Tell me about Eilat")
    assistant.ask("u1", "12*(3+4)")
    assistant.ask("u1", "And its beaches?")
    assert len(isolated_memory.get_history("u1")) == 6
    assert "12*(3+4)" in fakes["rag"][1][1]          # arithmetic turn is visible to later turns


def test_smalltalk_costs_nothing(monkeypatch):
    monkeypatch.setattr(chat, "get_structured", lambda *a: pytest.fail("LLM called"))
    monkeypatch.setattr(tool_agent, "get_answer", lambda *a: pytest.fail("LLM called"))
    monkeypatch.setattr("rag.get_relevant_chunks", lambda *a, **k: pytest.fail("retrieval called"))
    assert assistant.ask("u1", "hello")["source"] == "smalltalk"


def test_api_ask_end_to_end(fakes):
    client = TestClient(app)
    r = client.post("/ask", json={"session_id": "e2e", "query": "Tell me about Eilat"})
    assert r.status_code == 200 and r.json()["results"]["source"] == "rag"
    assert client.post("/ask", json={"session_id": "bad id", "query": "x y"}).status_code == 422
    assert client.post("/ask", json={"session_id": "e2e", "query": ""}).status_code == 422
    r = client.post("/ask", json={"session_id": "e2e", "query": "12*(3+4)"})
    assert r.json()["results"]["tool"]["output"] == 84.0
