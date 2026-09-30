"""Offline tests for Day 12 session memory and multi-turn chat (LLM mocked)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import chat
import prompts
from errors import ExternalServiceError
from main import app
from memory import InvalidSessionError, MemoryStore, validate_session_id


# --- store ---------------------------------------------------------------------------------
def test_add_and_get_history(tmp_path):
    m = MemoryStore(tmp_path / "s.json")
    assert m.add_turn("a", "hi", "hello") == 1
    assert [x["role"] for x in m.get_history("a")] == ["user", "assistant"]
    assert m.get_history("unknown") == []


def test_history_is_bounded_to_max_turns(tmp_path):
    m = MemoryStore(tmp_path / "s.json", max_turns=2)
    for i in range(5):
        m.add_turn("a", f"q{i}", f"a{i}")
    assert [x["content"] for x in m.get_history("a")] == ["q3", "a3", "q4", "a4"]


def test_sessions_are_isolated(tmp_path):
    m = MemoryStore(tmp_path / "s.json")
    m.add_turn("a", "qa", "aa")
    m.add_turn("b", "qb", "ab")
    assert m.get_history("a")[0]["content"] == "qa" and m.get_history("b")[0]["content"] == "qb"


def test_lru_eviction(tmp_path):
    m = MemoryStore(tmp_path / "s.json", max_sessions=2)
    m.add_turn("a", "1", "1")
    m.add_turn("b", "2", "2")
    m.add_turn("a", "3", "3")   # touch a -> b is now the oldest
    m.add_turn("c", "4", "4")
    assert m.get_history("b") == [] and m.get_history("a") and m.get_history("c")


def test_persistence_roundtrip_and_clear(tmp_path):
    path = tmp_path / "s.json"
    MemoryStore(path).add_turn("a", "hello", "world")
    reopened = MemoryStore(path)
    assert reopened.get_history("a")[1]["content"] == "world"
    assert reopened.clear("a") is True and reopened.clear("a") is False
    assert MemoryStore(path).get_history("a") == []


def test_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf8")
    assert MemoryStore(path).get_history("a") == []


def test_prompt_formatting_respects_budget(tmp_path):
    m = MemoryStore(tmp_path / "s.json")
    m.add_turn("a", "first question", "first answer")
    m.add_turn("a", "second question", "second answer")
    full = m.format_for_prompt("a", max_chars=1000).splitlines()
    assert full[0] == "User: first question" and full[-1] == "Assistant: second answer"
    small = m.format_for_prompt("a", max_chars=40)
    assert "second answer" in small and "first question" not in small   # newest kept, oldest dropped


@pytest.mark.parametrize("sid", ["", "a b", "../x", "x" * 65, "a/b"])
def test_invalid_session_ids(sid):
    with pytest.raises(InvalidSessionError):
        validate_session_id(sid)


# --- follow-up detection / rewrite ------------------------------------------------------------
def test_needs_rewrite_only_with_history_and_reference():
    assert not chat.needs_rewrite("What about its beaches?", "")                 # no history
    assert chat.needs_rewrite("What about its beaches?", "User: x")
    assert chat.needs_rewrite("Why is Jerusalem holy to so many religions and what is there", "User: x")  # 'there'
    assert not chat.needs_rewrite("Describe the geology of the Ramon Crater in detail please", "User: x")


def test_rewrite_failure_falls_back(monkeypatch):
    def boom(*a):
        raise ExternalServiceError()

    monkeypatch.setattr(chat, "get_structured", boom)
    assert chat.rewrite_question("and its beaches?", "User: Eilat") == "and its beaches?"


def test_memory_block_in_prompt_only_when_history():
    assert "Conversation so far" not in prompts.render_rag_prompt("ctx", "q")
    p = prompts.render_rag_prompt("ctx", "q", "User: hi")
    assert p.startswith("Conversation so far") and "<context>" in p


# --- chat flow ------------------------------------------------------------------------------------
@pytest.fixture
def fake_rag(monkeypatch):
    calls = []

    def rag(question, top_k, filters, history):
        calls.append({"question": question, "history": history})
        return {"answer": f"answer to: {question}", "source": "rag", "retrieved_chunks": []}

    monkeypatch.setattr(chat, "get_rag_answer", rag)
    monkeypatch.setattr(chat, "get_structured", lambda p, s, n: {"question": "What are the beaches like in Eilat?"})
    return calls


def test_first_turn_has_no_memory_and_is_saved(fake_rag, isolated_memory):
    r = chat.chat("s1", "Tell me about Eilat")
    assert r["session"]["used_memory"] is False and fake_rag[0]["history"] == ""
    assert len(isolated_memory.get_history("s1")) == 2


def test_follow_up_is_rewritten_and_gets_history(fake_rag):
    chat.chat("s1", "Tell me about Eilat")
    r = chat.chat("s1", "And its beaches?")
    assert r["session"]["standalone_question"] == "What are the beaches like in Eilat?"
    assert r["question"] == "And its beaches?"                                    # user sees their own words
    assert "Tell me about Eilat" in fake_rag[1]["history"]
    assert fake_rag[1]["question"] == "What are the beaches like in Eilat?"


def test_smalltalk_does_not_trigger_rewrite(fake_rag, monkeypatch):
    chat.chat("s1", "Tell me about Eilat")
    monkeypatch.setattr(chat, "get_structured", lambda *a: pytest.fail("rewrite called for smalltalk"))
    chat.chat("s1", "thanks")


def test_other_session_does_not_see_history(fake_rag):
    chat.chat("s1", "Tell me about Eilat")
    chat.chat("s2", "And its beaches?")
    assert fake_rag[1]["history"] == ""


def test_invalid_session_rejected_before_anything_runs(monkeypatch):
    monkeypatch.setattr(chat, "get_rag_answer", lambda *a: pytest.fail("pipeline ran"))
    with pytest.raises(InvalidSessionError):
        chat.chat("bad id!", "hello")


# --- API -----------------------------------------------------------------------------------------------
def test_chat_api_flow(fake_rag):
    client = TestClient(app)
    r = client.post("/chat", json={"session_id": "api-1", "query": "Tell me about Eilat"})
    assert r.status_code == 200 and r.json()["results"]["session"]["turns_before"] == 0
    r = client.post("/chat", json={"session_id": "api-1", "query": "And its beaches?"})
    assert r.json()["results"]["session"]["turns_before"] == 1
    assert client.get("/session/api-1").json()["turns"] == 2
    assert client.delete("/session/api-1").json()["deleted"] is True
    assert client.get("/session/api-1").json()["turns"] == 0


def test_chat_api_rejects_bad_session_id():
    assert TestClient(app).post("/chat", json={"session_id": "bad id!", "query": "hi"}).status_code == 422
