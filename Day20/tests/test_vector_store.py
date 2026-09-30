"""Offline tests for the FAISS vector store (synthetic 3-d vectors, no API calls)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import retrieval
from errors import DataStoreError
from similarity import cosine_similarity
from vector_store import VectorStore

CHUNKS = [
    {"doc_id": 1, "chunk_id": 0, "text": "alpha city", "embedded_text": [1.0, 0.0, 0.0]},
    {"doc_id": 2, "chunk_id": 0, "text": "beta desert", "embedded_text": [0.0, 1.0, 0.0]},
    {"doc_id": 3, "chunk_id": 0, "text": "gamma sea", "embedded_text": [0.7, 0.7, 0.0]},
]


def test_search_orders_by_cosine_and_matches_pure_python():
    store = VectorStore.build(CHUNKS)
    hits = store.search([1.0, 0.1, 0.0], k=3)
    assert [h["doc_id"] for h in hits] == [1, 3, 2]
    for hit, chunk in zip(hits, [CHUNKS[0], CHUNKS[2], CHUNKS[1]]):
        assert hit["similarity"] == pytest.approx(cosine_similarity([1.0, 0.1, 0.0], chunk["embedded_text"]), abs=1e-5)


def test_search_k_larger_than_index_is_clamped():
    assert len(VectorStore.build(CHUNKS).search([1, 0, 0], k=50)) == 3


def test_metadata_excludes_vectors():
    assert "embedded_text" not in VectorStore.build(CHUNKS).metadata[0]


def test_save_and_load_roundtrip(tmp_path):
    store = VectorStore.build(CHUNKS)
    store.save(tmp_path / "i.index", tmp_path / "m.json")
    loaded = VectorStore.load(tmp_path / "i.index", tmp_path / "m.json")
    assert loaded.search([0, 1, 0], k=1)[0]["doc_id"] == 2


def test_load_missing_or_out_of_sync_files_raise(tmp_path):
    with pytest.raises(DataStoreError):
        VectorStore.load(tmp_path / "nope.index", tmp_path / "nope.json")
    store = VectorStore.build(CHUNKS)
    store.save(tmp_path / "i.index", tmp_path / "m.json")
    (tmp_path / "m.json").write_text("[]", encoding="utf8")
    with pytest.raises(DataStoreError):
        VectorStore.load(tmp_path / "i.index", tmp_path / "m.json")


def test_build_from_empty_raises():
    with pytest.raises(DataStoreError):
        VectorStore.build([])


def test_get_relevant_chunks_uses_faiss_and_filters(monkeypatch):
    monkeypatch.setattr(retrieval, "get_embedding", lambda q: [1.0, 0.0, 0.0])
    monkeypatch.setattr(retrieval, "get_store", lambda: VectorStore.build(CHUNKS))
    results = retrieval.get_relevant_chunks("alpha city", top_k=3)
    assert results[0]["doc_id"] == 1
    assert all(r["score"] >= retrieval.settings.min_chunk_score for r in results)  # orthogonal chunk dropped
    assert 2 not in [r["doc_id"] for r in results]
