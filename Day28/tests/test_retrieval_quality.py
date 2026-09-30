"""Offline tests for Day 9 ranking, metadata filtering, adaptive top-k and context formatting."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import rag
import retrieval
from schemas import SearchRequest
from vector_store import VectorStore

CHUNKS = [
    {"doc_id": 1, "chunk_id": 0, "topic": "Masada", "category": "history", "text": "Masada fortress on a plateau", "embedded_text": [1.0, 0.0, 0.0]},
    {"doc_id": 2, "chunk_id": 0, "topic": "Dead Sea", "category": "nature", "text": "Dead Sea salt lake", "embedded_text": [0.9, 0.3, 0.0]},
    {"doc_id": 3, "chunk_id": 0, "topic": "Haifa", "category": "city", "text": "Haifa port on Carmel", "embedded_text": [0.0, 1.0, 0.0]},
]


@pytest.fixture
def store(monkeypatch):
    s = VectorStore.build(CHUNKS)
    monkeypatch.setattr(retrieval, "get_store", lambda: s)
    monkeypatch.setattr(retrieval, "get_embedding", lambda q: [1.0, 0.2, 0.0])
    return s


def test_topic_boost_only_when_topic_named():
    base = retrieval.score_chunk("salt lake", "Dead Sea salt lake", 0.5, "Dead Sea")
    named = retrieval.score_chunk("tell me about the dead sea", "Dead Sea salt lake", 0.5, "Dead Sea")
    assert named - base >= retrieval.settings.topic_boost - 0.11  # keyword part differs slightly
    assert retrieval.topic_in_query("Tell me about the DEAD SEA", "Dead Sea")
    assert not retrieval.topic_in_query("tell me about seas", "Dead Sea")
    assert not retrieval.topic_in_query("anything", None)


def test_relative_cutoff_drops_noisy_tail():
    chunks = [{"score": 0.80}, {"score": 0.75}, {"score": 0.40}]
    assert [c["score"] for c in retrieval.relative_cutoff(chunks)] == [0.80, 0.75]
    assert retrieval.relative_cutoff([]) == []


def test_matches_filters_case_insensitive_and_all_fields():
    chunk = {"category": "Nature", "topic": "Dead Sea"}
    assert retrieval.matches_filters(chunk, {"category": "nature"})
    assert retrieval.matches_filters(chunk, {"category": "nature", "topic": "dead sea"})
    assert not retrieval.matches_filters(chunk, {"category": "city"})
    assert retrieval.matches_filters(chunk, None)


def test_metadata_filter_restricts_results(store):
    results = retrieval.get_relevant_chunks("plateau", 3, {"category": "nature"})
    assert results and {r["category"] for r in results} == {"nature"}


def test_filter_with_no_match_returns_empty(store):
    assert retrieval.get_relevant_chunks("plateau", 3, {"category": "society"}) == []


def test_results_carry_metadata(store):
    top = retrieval.get_relevant_chunks("masada plateau", 3)[0]
    assert top["topic"] == "Masada" and top["category"] == "history"


def test_context_includes_topic_and_orders_as_given():
    ctx = rag.build_context([{"doc_id": 1, "chunk_id": 0, "topic": "Masada", "text": "A"},
                             {"doc_id": 2, "chunk_id": 1, "topic": "Dead Sea", "text": "B"}])
    assert ctx.splitlines() == ["[1:0|Masada] A", "[2:1|Dead Sea] B"]


def test_search_request_filters_helper():
    assert SearchRequest(query="x").filters() is None
    assert SearchRequest(query="x", category="nature").filters() == {"category": "nature"}
    assert SearchRequest(query="x", category="nature", topic="Masada").filters() == {"category": "nature", "topic": "Masada"}
