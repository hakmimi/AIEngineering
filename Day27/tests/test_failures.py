"""Offline failure-injection tests for Day 18: safe nodes, retries, fallback path."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import graph
import prompts
from errors import ExternalServiceError
from resilience import retry_call

CHUNK = {"doc_id": 1, "chunk_id": 0, "topic": "Masada", "text": "Masada is a fortress.", "score": 0.9, "similarity": 0.9}
GOOD = {"answer": "A fortress.", "confidence": 0.9, "score": None}


class Flaky:
    """Fails `failures` times with the given error, then succeeds."""

    def __init__(self, failures, error=None, result=GOOD):
        self.calls, self.failures, self.error, self.result = 0, failures, error or ExternalServiceError(), result

    def __call__(self, *a, **k):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return self.result


# --- retry policy ----------------------------------------------------------------------------------
def test_retry_succeeds_after_transient_failures():
    fn = Flaky(2)
    assert retry_call(fn, label="t", attempts=3, base_delay=0) == GOOD and fn.calls == 3


def test_retry_gives_up_after_max_attempts_and_reraises():
    fn = Flaky(99)
    with pytest.raises(ExternalServiceError):
        retry_call(fn, label="t", attempts=3, base_delay=0)
    assert fn.calls == 3


def test_non_retryable_error_is_not_retried():
    fn = Flaky(99, ExternalServiceError(retryable=False))
    with pytest.raises(ExternalServiceError):
        retry_call(fn, label="t", attempts=3, base_delay=0)
    assert fn.calls == 1


def test_other_exceptions_are_not_retried():
    fn = Flaky(99, ValueError("bug"))
    with pytest.raises(ValueError):
        retry_call(fn, label="t", attempts=3, base_delay=0)
    assert fn.calls == 1


# --- graph: recovery -----------------------------------------------------------------------------------
def test_llm_recovers_after_one_transient_failure(monkeypatch):
    llm = Flaky(1)
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: [CHUNK])
    monkeypatch.setattr(graph, "get_answer", llm)
    r = graph.run_graph("Where is Masada?")
    assert r["source"] == "rag" and llm.calls == 2 and "error" not in r


def test_retrieval_recovers_after_one_transient_failure(monkeypatch):
    retrieval = Flaky(1, result=[CHUNK])
    monkeypatch.setattr(graph, "get_relevant_chunks", retrieval)
    monkeypatch.setattr(graph, "get_answer", lambda p: GOOD)
    assert graph.run_graph("Where is Masada?")["source"] == "rag" and retrieval.calls == 2


# --- graph: fallback --------------------------------------------------------------------------------------
def test_persistent_llm_failure_degrades_to_evidence(monkeypatch):
    llm = Flaky(99)
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: [CHUNK])
    monkeypatch.setattr(graph, "get_answer", llm)
    r = graph.run_graph("Where is Masada?")
    assert r["source"] == "fallback_error" and llm.calls == 3
    assert "Masada is a fortress." in r["answer"]                         # best evidence still shown
    assert r["error"] == {"node": "call_llm", "type": "ExternalServiceError",
                          "message": "External AI service is unavailable", "retryable": True}
    assert r["graph"]["trace"][-2:] == ["call_llm", "fallback_node"]


def test_persistent_retrieval_failure_goes_to_fallback_without_calling_llm(monkeypatch):
    monkeypatch.setattr(graph, "get_relevant_chunks", Flaky(99))
    monkeypatch.setattr(graph, "get_answer", lambda p: pytest.fail("LLM called after retrieval failed"))
    r = graph.run_graph("Where is Masada?")
    assert r["source"] == "fallback_error" and r["answer"] == prompts.LLM_DOWN_ANSWER
    assert r["error"]["node"] == "retrieve_context"


def test_unexpected_bug_in_a_node_is_contained(monkeypatch):
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: 1 / 0)
    r = graph.run_graph("Where is Masada?")
    assert r["source"] == "fallback_error" and r["error"]["type"] == "ZeroDivisionError" and r["error"]["retryable"] is False


def test_non_retryable_failure_is_not_retried_by_the_graph(monkeypatch):
    llm = Flaky(99, ExternalServiceError(retryable=False))
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: [CHUNK])
    monkeypatch.setattr(graph, "get_answer", llm)
    r = graph.run_graph("Where is Masada?")
    assert llm.calls == 1 and r["error"]["retryable"] is False


def test_tool_failure_goes_to_fallback(monkeypatch):
    monkeypatch.setattr(graph, "execute_tool", lambda n, a: 1 / 0)
    r = graph.run_graph("12*(3+4)")
    assert r["source"] == "fallback_error" and "calculation or lookup" in r["answer"] and r["error"]["node"] == "run_tool"


def test_weak_context_is_a_refusal_not_an_error(monkeypatch):
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: [])
    monkeypatch.setattr(graph, "get_answer", lambda p: pytest.fail("LLM called"))
    r = graph.run_graph("What is the capital of France?")
    assert r["source"] == "no_context" and "error" not in r


def test_degraded_answer_variants():
    assert prompts.render_degraded_answer([], {"node": "call_llm"}) == prompts.LLM_DOWN_ANSWER
    assert "Masada is a fortress." in prompts.render_degraded_answer([CHUNK], {"node": "call_llm"})
    assert "calculation" in prompts.render_degraded_answer([], {"node": "run_tool"})


def test_graph_has_fallback_edges():
    g = graph.rag_graph.get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    assert {("retrieve_context", "fallback_node"), ("call_llm", "fallback_node"), ("run_tool", "fallback_node")} <= edges
    assert ("fallback_node", "finish") in edges
