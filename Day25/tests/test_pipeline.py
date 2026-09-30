"""Offline tests for the Day 10 multi-step pipeline (LLM + retrieval mocked)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import pipeline
from errors import ExternalServiceError
from main import app

CHUNK = {"doc_id": 1, "chunk_id": 0, "topic": "Masada", "text": "Masada is a fortress.", "score": 0.9, "similarity": 0.9}


def fake_llm(calls):
    def _fake(prompt, schema, name):
        calls.append(name)
        return {
            "analyze": {"search_query": "Masada location", "intent": "lookup"},
            "extract": {"facts": [{"tag": "1:0|Masada", "sentence": "Masada is a fortress."}]},
            "compose": {"answer": "It is a fortress [1:0].", "confidence": 0.9, "score": None},
        }[name]
    return _fake


def test_steps_run_in_order_with_distinct_prompts(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "get_structured", fake_llm(calls))
    monkeypatch.setattr(pipeline, "get_relevant_chunks", lambda q, k, f=None, wide=False: [CHUNK])
    result = pipeline.run_pipeline("Where is Masada?")
    assert calls == ["analyze", "extract", "compose"]
    assert [t["step"] for t in result["pipeline"]["trace"]] == ["analyze", "retrieve", "extract", "compose"]
    assert result["source"] == "multistep" and result["answer"].startswith("It is a fortress")
    assert {"analyze", "retrieve", "extract", "compose"} <= set(result["timings"])


def test_retrieval_uses_rewritten_query(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "get_structured", fake_llm([]))
    monkeypatch.setattr(pipeline, "get_relevant_chunks", lambda q, k, f=None, wide=False: seen.append(q) or [CHUNK])
    pipeline.run_pipeline("Where is Masada?")
    assert seen == ["Masada location"]


def test_empty_rewrite_result_retries_with_original(monkeypatch):
    seen = []

    def chunks(q, k, f=None):
        seen.append(q)
        return [] if q == "Masada location" else [CHUNK]

    monkeypatch.setattr(pipeline, "get_structured", fake_llm([]))
    monkeypatch.setattr(pipeline, "get_relevant_chunks", chunks)
    result = pipeline.run_pipeline("Where is Masada?")
    assert seen == ["Masada location", "Where is Masada?"] and result["source"] == "multistep"


def test_no_context_stops_before_extract_and_compose(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "get_structured", fake_llm(calls))
    monkeypatch.setattr(pipeline, "get_relevant_chunks", lambda q, k, f=None, wide=False: [])
    result = pipeline.run_pipeline("What is the capital of France?")
    assert calls == ["analyze"] and result["source"] == "no_context"


def test_no_facts_stops_before_compose(monkeypatch):
    calls = []

    def llm(prompt, schema, name):
        calls.append(name)
        return {"analyze": {"search_query": "x y", "intent": "open"}, "extract": {"facts": []}}[name]

    monkeypatch.setattr(pipeline, "get_structured", llm)
    monkeypatch.setattr(pipeline, "get_relevant_chunks", lambda q, k, f=None, wide=False: [CHUNK])
    assert pipeline.run_pipeline("Where is Masada?")["source"] == "no_context" and "compose" not in calls


def test_analyze_failure_degrades_to_raw_question(monkeypatch):
    seen = []

    def llm(prompt, schema, name):
        if name == "analyze":
            raise ExternalServiceError()
        return fake_llm([])(prompt, schema, name)

    monkeypatch.setattr(pipeline, "get_structured", llm)
    monkeypatch.setattr(pipeline, "get_relevant_chunks", lambda q, k, f=None, wide=False: seen.append(q) or [CHUNK])
    assert pipeline.run_pipeline("Where is Masada?")["source"] == "multistep" and seen == ["Where is Masada?"]


def test_late_step_failure_returns_fallback(monkeypatch):
    def llm(prompt, schema, name):
        if name == "compose":
            raise ExternalServiceError()
        return fake_llm([])(prompt, schema, name)

    monkeypatch.setattr(pipeline, "get_structured", llm)
    monkeypatch.setattr(pipeline, "get_relevant_chunks", lambda q, k, f=None, wide=False: [CHUNK])
    result = pipeline.run_pipeline("Where is Masada?")
    assert result["source"] == "fallback_error"


def test_comparison_intent_widens_top_k(monkeypatch):
    ks = []

    def llm(prompt, schema, name):
        return {"analyze": {"search_query": "a b", "intent": "comparison"}}.get(name) or fake_llm([])(prompt, schema, name)

    monkeypatch.setattr(pipeline, "get_structured", llm)
    monkeypatch.setattr(pipeline, "get_relevant_chunks", lambda q, k, f=None, wide=False: ks.append(k) or [CHUNK])
    pipeline.run_pipeline("Compare Haifa and Eilat", top_k=2)
    assert ks[0] >= 6


def test_smalltalk_skips_all_llm_calls(monkeypatch):
    monkeypatch.setattr(pipeline, "get_structured", lambda *a: pytest.fail("LLM called"))
    assert pipeline.run_pipeline("hello")["source"] == "smalltalk"


def test_multistep_endpoint(monkeypatch):
    monkeypatch.setattr(pipeline, "get_structured", fake_llm([]))
    monkeypatch.setattr(pipeline, "get_relevant_chunks", lambda q, k, f=None, wide=False: [CHUNK])
    resp = TestClient(app).post("/rag/multistep", json={"query": "Where is Masada?"})
    assert resp.status_code == 200 and resp.json()["results"]["pipeline"]["trace"]
