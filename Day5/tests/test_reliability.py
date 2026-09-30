"""Offline edge-case tests for Day 5 (no OpenAI calls: everything external is mocked)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient

import rag
import retrieval
from chunk import chunk_text, clean_text
from errors import ExternalServiceError
from main import app


def chunk(score, text="Jerusalem is a sacred city.", doc_id=1, chunk_id=0):
    return {"doc_id": doc_id, "chunk_id": chunk_id, "text": text, "score": score, "similarity": score}


# --- data cleaning -------------------------------------------------------
def test_clean_text_strips_noise():
    assert clean_text("  Hello\n\n<b>world</b>\t!\x00 ") == "Hello world !"


def test_chunk_text_drops_tiny_tail():
    words = " ".join(f"w{i}" for i in range(32))  # 30 + tail of 2 words
    assert len(chunk_text(words)) == 1


# --- scoring / filtering -------------------------------------------------
def test_keyword_overlap_boosts_score():
    with_kw = retrieval.score_chunk("Jerusalem Western Wall", "The Western Wall in Jerusalem", 0.5)
    without = retrieval.score_chunk("Jerusalem Western Wall", "Beaches of Eilat", 0.5)
    assert with_kw > without == 0.5


def test_filter_chunks_removes_low_scores():
    kept = retrieval.filter_chunks([chunk(0.9), chunk(0.1)])
    assert [c["score"] for c in kept] == [0.9]


# --- validation gate -----------------------------------------------------
def test_validate_context_blocks_empty_and_weak():
    assert not rag.validate_context([])
    assert not rag.validate_context([chunk(0.40)])
    assert rag.validate_context([chunk(0.80)])


def test_empty_question_never_hits_retrieval_or_llm(monkeypatch):
    monkeypatch.setattr(rag, "get_relevant_chunks", lambda *a: pytest.fail("retrieval called"))
    result = rag.get_rag_answer("   ")
    assert result["source"] == "invalid_input"


def test_low_quality_context_blocks_llm(monkeypatch):
    monkeypatch.setattr(rag, "get_relevant_chunks", lambda q, k: [chunk(0.35)])
    monkeypatch.setattr(rag, "get_answer", lambda p: pytest.fail("LLM called"))
    result = rag.get_rag_answer("Tell me about Lumaria")
    assert result["source"] == "no_context"
    assert result["answer"] == rag.NO_CONTEXT_ANSWER


# --- LLM failure / fallback ----------------------------------------------
def test_llm_failure_returns_fallback_not_exception(monkeypatch):
    def boom(prompt):
        raise ExternalServiceError()

    monkeypatch.setattr(rag, "get_relevant_chunks", lambda q, k: [chunk(0.9)])
    monkeypatch.setattr(rag, "get_answer", boom)
    result = rag.get_rag_answer("Why is Jerusalem important?")
    assert result["source"] == "fallback_error"
    assert result["answer"] == rag.LLM_DOWN_ANSWER


def test_happy_path(monkeypatch):
    monkeypatch.setattr(rag, "get_relevant_chunks", lambda q, k: [chunk(0.9)])
    monkeypatch.setattr(rag, "get_answer", lambda p: {"answer": "Sacred to three faiths.", "confidence": 0.9, "score": 1})
    result = rag.get_rag_answer("Why is Jerusalem important?")
    assert result["source"] == "rag" and result["retrieved_chunks"]


def test_prompt_contains_grounding_rules():
    prompt = rag.RAG_PROMPT.format(no_context="X", context="ctx", question="q")
    assert "<context>" in prompt and "ONLY" in prompt


# --- API edge cases ------------------------------------------------------
client = TestClient(app, raise_server_exceptions=False)


def test_api_rejects_empty_query():
    assert client.post("/rag", json={"query": "", "top_k": 3}).status_code == 422


def test_api_rejects_bad_top_k():
    assert client.post("/rag", json={"query": "hi", "top_k": 999}).status_code == 422


def test_api_rejects_missing_body():
    assert client.post("/rag", json={}).status_code == 422


def test_api_rag_no_context_is_200(monkeypatch):
    monkeypatch.setattr(rag, "get_relevant_chunks", lambda q, k: [])
    resp = client.post("/rag", json={"query": "Tell me about Lumaria"})
    assert resp.status_code == 200
    assert resp.json()["results"]["source"] == "no_context"


def test_api_unexpected_error_is_safe(monkeypatch):
    import main
    monkeypatch.setattr(main, "get_rag_answer", lambda q, k: 1 / 0)
    resp = client.post("/rag", json={"query": "hi"})
    assert resp.status_code == 500 and resp.json() == {"detail": "Internal server error"}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}
