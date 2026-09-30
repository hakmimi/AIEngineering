"""Offline tests for Day 6 routing + timing (no OpenAI calls)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import rag
from main import app
from router import CLARIFY, RAG_COMPLEX, RAG_SIMPLE, SKIP, route_query
from timing import StepTimer


def chunk(score=0.9):
    return {"doc_id": 1, "chunk_id": 0, "text": "Jerusalem is sacred.", "score": score, "similarity": score}


# --- router --------------------------------------------------------------
@pytest.mark.parametrize("q,expected", [
    ("hello", SKIP), ("thanks", SKIP), ("Hi there", SKIP),
    ("Jerusalem", CLARIFY), ("", CLARIFY),
    ("Where is Masada?", RAG_SIMPLE),
    ("Compare Tel Aviv and Haifa", RAG_COMPLEX),
    ("Why is Jerusalem so important?", RAG_SIMPLE),
])
def test_route_classification(q, expected):
    assert route_query(q, 4).name == expected


def test_simple_route_caps_top_k_and_complex_raises_it():
    assert route_query("Where is Masada?", 10).top_k == 3
    assert route_query("Compare Tel Aviv and Haifa", 2).top_k >= 6


def test_hello_inside_real_question_is_not_smalltalk():
    assert route_query("hello can you explain the Dead Sea salt levels in detail please", 4).name == RAG_COMPLEX


# --- skip paths cost nothing ---------------------------------------------
def test_smalltalk_skips_retrieval_and_llm(monkeypatch):
    monkeypatch.setattr(rag, "get_relevant_chunks", lambda *a: pytest.fail("retrieval called"))
    monkeypatch.setattr(rag, "get_answer", lambda p: pytest.fail("LLM called"))
    result = rag.get_rag_answer("hello")
    assert result["source"] == "smalltalk" and result["route"] == SKIP
    assert "retrieval" not in result["timings"] and "llm" not in result["timings"]


def test_clarify_skips_pipeline(monkeypatch):
    monkeypatch.setattr(rag, "get_relevant_chunks", lambda *a: pytest.fail("retrieval called"))
    assert rag.get_rag_answer("Jerusalem")["source"] == "invalid_input"


# --- per-step timings ----------------------------------------------------
def test_full_path_reports_each_step(monkeypatch):
    monkeypatch.setattr(rag, "get_relevant_chunks", lambda q, k, f=None, wide=False: [chunk()])
    monkeypatch.setattr(rag, "get_answer", lambda p: {"answer": "ok", "confidence": 0.9, "score": 1})
    result = rag.get_rag_answer("Where is Masada?")
    assert {"routing", "retrieval", "prompt", "llm", "total_ms"} <= set(result["timings"])
    assert result["route"] == RAG_SIMPLE


def test_step_timer_measures_and_finds_slowest():
    t = StepTimer()
    with t.step("fast"):
        pass
    with t.step("slow"):
        time.sleep(0.02)
    assert t.slowest() == "slow" and t.report()["slow"] >= 15


def test_step_timer_records_on_exception():
    t = StepTimer()
    with pytest.raises(ValueError):
        with t.step("boom"):
            raise ValueError
    assert "boom" in t.steps


# --- prompt size ---------------------------------------------------------
def test_prompt_is_compact():
    prompt = rag.RAG_PROMPT.format(no_context=rag.NO_CONTEXT_ANSWER, context="", question="")
    assert len(prompt) < 350
    assert rag.build_context([chunk()]).startswith("[1:0|")


# --- API -----------------------------------------------------------------
def test_latency_header_present():
    resp = TestClient(app).get("/health")
    assert float(resp.headers["X-Process-Time-Ms"]) >= 0
