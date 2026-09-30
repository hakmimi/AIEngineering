"""Offline tests for Day 24: usage/cost tracking and the token-aware context cap."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import embeddings
import graph
import llm
import rag
import usage
from usage import UsageTracker, estimate_cost, estimate_tokens, record_usage, start_tracking, stop_tracking


# --- pricing math ---------------------------------------------------------------------------------------
def test_estimate_cost_per_million_tokens():
    assert estimate_cost("gpt-4.1-mini", 1_000_000, 0) == pytest.approx(0.40)
    assert estimate_cost("gpt-4.1-mini", 0, 1_000_000) == pytest.approx(1.60)
    assert estimate_cost("gpt-4.1-mini", 250, 30) == pytest.approx((250 * 0.40 + 30 * 1.60) / 1e6)
    assert estimate_cost("text-embedding-3-small", 1_000_000) == pytest.approx(0.02)


def test_unknown_model_costs_zero_not_crash():
    assert estimate_cost("some-new-model", 1000, 1000) == 0.0


def test_token_estimate():
    assert estimate_tokens("") == 0 and estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2


# --- tracker ---------------------------------------------------------------------------------------------
def test_tracker_sums_calls_by_kind():
    t = UsageTracker()
    t.add("llm", "rag_answer", "gpt-4.1-mini", 250, 30)
    t.add("llm", "rewrite", "gpt-4.1-mini", 100, 10)
    t.add("embedding", "query", "text-embedding-3-small", 6)
    s = t.summary()
    assert (s["llm_calls"], s["embedding_calls"]) == (2, 1)
    assert (s["llm_input_tokens"], s["llm_output_tokens"], s["embedding_tokens"]) == (350, 40, 6)
    assert s["estimated_cost_usd"] == pytest.approx((350 * 0.40 + 40 * 1.60 + 6 * 0.02) / 1e6, abs=1e-6)


def test_record_usage_goes_to_the_current_tracker_only_while_tracking():
    record_usage("llm", "x", "gpt-4.1-mini", 10, 1)          # no tracker: must not raise
    tracker, token = start_tracking()
    record_usage("llm", "x", "gpt-4.1-mini", 10, 1)
    stop_tracking(token)
    record_usage("llm", "x", "gpt-4.1-mini", 10, 1)          # after stop: not counted
    assert tracker.summary()["llm_calls"] == 1


# --- provider responses feed the tracker -------------------------------------------------------------------
class FakeClient:
    def __init__(self, usage_obj):
        self.responses = SimpleNamespace(create=lambda **kw: SimpleNamespace(
            output_text='{"answer": "ok", "confidence": 0.9, "score": null}', usage=usage_obj))
        self.embeddings = SimpleNamespace(create=lambda **kw: SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.1, 0.2])], usage=usage_obj))


def test_llm_and_embedding_calls_are_recorded(monkeypatch):
    fake = FakeClient(SimpleNamespace(input_tokens=120, output_tokens=15, prompt_tokens=7))
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    monkeypatch.setattr(embeddings, "get_client", lambda: fake)
    tracker, token = start_tracking()
    llm.get_answer("prompt")
    embeddings.get_embedding("text")
    stop_tracking(token)
    s = tracker.summary()
    assert s["llm_input_tokens"] == 120 and s["llm_output_tokens"] == 15 and s["embedding_tokens"] == 7


def test_missing_usage_field_does_not_break_the_call(monkeypatch):
    monkeypatch.setattr(llm, "get_client", lambda: FakeClient(None))
    assert llm.get_answer("prompt")["answer"] == "ok"


def test_schema_only_in_prompt_when_enabled(monkeypatch):
    seen = []
    fake = FakeClient(None)
    fake.responses = SimpleNamespace(create=lambda **kw: seen.append(kw["input"]) or SimpleNamespace(
        output_text='{"answer": "a", "confidence": 1, "score": null}', usage=None))
    monkeypatch.setattr(llm, "get_client", lambda: fake)
    object.__setattr__(llm.settings, "json_schema_in_prompt", False)
    llm.get_answer("PROMPT")
    object.__setattr__(llm.settings, "json_schema_in_prompt", True)
    try:
        llm.get_answer("PROMPT")
    finally:
        object.__setattr__(llm.settings, "json_schema_in_prompt", False)
    assert seen[0] == "PROMPT" and "Return only valid JSON" in seen[1] and len(seen[1]) > len(seen[0]) + 100


# --- token-aware context cap ---------------------------------------------------------------------------------
def _chunks(n, words=40):
    return [{"doc_id": i, "chunk_id": 0, "topic": f"T{i}", "text": ("word " * words).strip()} for i in range(n)]


def test_context_cap_keeps_whole_chunks_best_first(monkeypatch):
    object.__setattr__(rag.settings, "max_context_tokens", 100)
    try:
        ctx = rag.build_context(_chunks(6))            # each line is ~ 55 tokens -> only 1 fits
        assert ctx.count("[") == 1 and ctx.startswith("[0:0|T0]")
        assert ctx.endswith("word")                     # cut between chunks, never inside one
    finally:
        object.__setattr__(rag.settings, "max_context_tokens", 400)


def test_context_cap_always_keeps_at_least_one_chunk():
    object.__setattr__(rag.settings, "max_context_tokens", 5)
    try:
        assert rag.build_context(_chunks(3)).startswith("[0:0|T0]")
    finally:
        object.__setattr__(rag.settings, "max_context_tokens", 400)


def test_zero_disables_the_token_cap():
    object.__setattr__(rag.settings, "max_context_tokens", 0)
    try:
        assert rag.build_context(_chunks(4)).count("[") == 4
    finally:
        object.__setattr__(rag.settings, "max_context_tokens", 400)


# --- graph response -------------------------------------------------------------------------------------------
def test_run_graph_returns_usage_and_logs_it(monkeypatch):
    monkeypatch.setattr(graph, "get_relevant_chunks", lambda *a, **k: [{"doc_id": 1, "chunk_id": 0, "topic": "M", "text": "t", "score": 0.9, "similarity": 0.9}])

    def fake_answer(prompt):
        record_usage("llm", "rag_answer", "gpt-4.1-mini", 200, 20)
        return {"answer": "ok", "confidence": 0.9, "score": None}

    monkeypatch.setattr(graph, "get_answer", fake_answer)
    r = graph.run_graph("Where is Masada?")
    assert r["usage"]["llm_input_tokens"] == 200 and r["usage"]["estimated_cost_usd"] > 0


def test_free_paths_cost_nothing():
    r = graph.run_graph("hello")
    assert r["usage"]["llm_calls"] == 0 and r["usage"]["estimated_cost_usd"] == 0


def test_price_override_env(monkeypatch):
    assert "gpt-4.1-mini" in usage.PRICES and usage.PRICES["gpt-4.1-mini"]["input"] == 0.40
