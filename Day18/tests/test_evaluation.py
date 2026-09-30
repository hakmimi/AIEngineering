"""Offline tests for the Day 13 evaluation scoring + sibling expansion."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from scripts import evaluate
import retrieval
from vector_store import VectorStore


# --- scoring functions ---------------------------------------------------------------------
@pytest.mark.parametrize("answer,expected", [
    ("I don't have enough information in my knowledge base to answer that.", True),
    ("The context does not provide information on X.", True),
    ("I don’t have enough information", True),
    ("Masada is a fortress.", False),
    (None, False),
])
def test_is_refusal(answer, expected):
    assert evaluate.is_refusal(answer) is expected


def test_keyword_score_groups_are_any_of_and_all_required():
    groups = [["Technion"], ["Weizmann", "Hebrew University"]]
    assert evaluate.keyword_score("The Technion and Weizmann Institute", groups) == 1.0
    assert evaluate.keyword_score("Only the Technion", groups) == 0.5
    assert evaluate.keyword_score("technion, hebrew university", groups) == 1.0   # case-insensitive
    assert evaluate.keyword_score("anything", []) == 1.0


def test_retrieval_hit_modes():
    assert evaluate.retrieval_hit(["A", "B"], ["A"], "any") is True
    assert evaluate.retrieval_hit(["A"], ["A", "B"], "any") is True
    assert evaluate.retrieval_hit(["A"], ["A", "B"], "all") is False
    assert evaluate.retrieval_hit(["A"], [], "any") is None


def _case(**kw):
    base = {"id": "q", "type": "fact", "question": "?", "expected_topics": ["A"], "topic_match": "any",
            "must_include": [["x"]], "should_refuse": False}
    return {**base, **kw}


def test_score_case_pass_and_fail_paths():
    good = evaluate.score_case(_case(), {"answer": "has x", "retrieved_chunks": [{"topic": "A"}]}, 10)
    assert good["passed"] and good["retrieval_hit"]
    wrong = evaluate.score_case(_case(), {"answer": "no match", "retrieved_chunks": []}, 10)
    assert not wrong["passed"] and wrong["retrieval_hit"] is False
    false_refusal = evaluate.score_case(_case(), {"answer": "not enough information", "retrieved_chunks": []}, 10)
    assert not false_refusal["passed"] and false_refusal["refused"]
    hallucination = evaluate.score_case(_case(should_refuse=True, expected_topics=[], must_include=[]),
                                        {"answer": "Paris!", "retrieved_chunks": []}, 10)
    assert not hallucination["passed"]
    ok_refusal = evaluate.score_case(_case(should_refuse=True, expected_topics=[], must_include=[]),
                                     {"answer": "not enough information", "retrieved_chunks": []}, 10)
    assert ok_refusal["passed"]


def test_summarize_rates():
    rows = [
        evaluate.score_case(_case(id="a"), {"answer": "x", "retrieved_chunks": [{"topic": "A"}]}, 100),
        evaluate.score_case(_case(id="b", should_refuse=True, expected_topics=[], must_include=[], type="out_of_domain"),
                            {"answer": "Paris", "retrieved_chunks": []}, 300),
    ]
    s = evaluate.summarize(rows)
    assert s["accuracy"] == 0.5 and s["hallucination_rate"] == 1.0 and s["false_refusal_rate"] == 0.0
    assert s["by_type"] == {"fact": 1.0, "out_of_domain": 0.0}


def test_eval_set_is_well_formed():
    cases = json.loads((evaluate.EVAL_DIR / "eval_set.json").read_text(encoding="utf8"))
    assert len(cases) >= 20 and len({c["id"] for c in cases}) == len(cases)
    types = {c["type"] for c in cases}
    assert {"fact", "comparison", "out_of_domain", "unanswerable_in_domain", "adversarial"} <= types
    for c in cases:
        assert c["should_refuse"] or c["must_include"], f"{c['id']} answerable but has no expected keywords"


# --- sibling expansion ---------------------------------------------------------------------------
CHUNKS = [
    {"doc_id": 1, "chunk_id": 0, "topic": "Masada", "category": "history", "text": "fortress", "embedded_text": [1, 0, 0]},
    {"doc_id": 1, "chunk_id": 1, "topic": "Masada", "category": "history", "text": "cable car", "embedded_text": [0.5, 0.5, 0]},
    {"doc_id": 2, "chunk_id": 0, "topic": "Haifa", "category": "city", "text": "port", "embedded_text": [0, 1, 0]},
]


def test_expand_adds_siblings_in_document_order_and_flags_them():
    store = VectorStore.build(CHUNKS)
    anchor = [{"doc_id": 1, "chunk_id": 0, "topic": "Masada", "text": "fortress", "similarity": 0.9, "score": 0.9}]
    out = retrieval.expand_with_siblings(anchor, store)
    assert [(c["doc_id"], c["chunk_id"], c["expanded"]) for c in out] == [(1, 0, False), (1, 1, True)]
    assert out[1]["score"] == 0.9          # sibling inherits the anchor score


def test_expand_groups_by_document_in_rank_order():
    store = VectorStore.build(CHUNKS)
    anchors = [{"doc_id": 2, "chunk_id": 0, "topic": "Haifa", "text": "port", "similarity": 0.8, "score": 0.8},
               {"doc_id": 1, "chunk_id": 1, "topic": "Masada", "text": "cable car", "similarity": 0.7, "score": 0.7}]
    out = retrieval.expand_with_siblings(anchors, store)
    assert [c["doc_id"] for c in out] == [2, 1, 1]        # Haifa (best) first, then Masada's chunks in order
    assert [c["chunk_id"] for c in out if c["doc_id"] == 1] == [0, 1]


def test_wide_margin_keeps_more_chunks():
    chunks = [{"score": 0.8}, {"score": 0.6}]
    assert len(retrieval.relative_cutoff(chunks)) == 1
    assert len(retrieval.relative_cutoff(chunks, margin=0.3)) == 2
