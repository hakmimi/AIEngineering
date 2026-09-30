"""Offline tests for the Day 20 evaluation runner (judge mocked) and prompt versioning."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

import prompts
from scripts import llm_eval

CASE = {"id": "q1", "category": "fact", "question": "Who built Caesarea?", "should_refuse": False,
        "key_facts": ["Herod"], "must_include": [["Herod"]], "expected_behavior": "Answer correctly."}
REFUSE = {**CASE, "id": "q2", "should_refuse": True, "key_facts": [], "must_include": []}


@pytest.fixture(autouse=True)
def restore_prompt_version():
    original = prompts.get_prompt_version()
    yield
    prompts.set_prompt_version(original)


# --- deterministic check ------------------------------------------------------------------------------
def test_keyword_pass_answerable():
    assert llm_eval.keyword_pass(CASE, "King Herod built it.")
    assert not llm_eval.keyword_pass(CASE, "A Roman governor built it.")
    assert not llm_eval.keyword_pass(CASE, "I don't have enough information about Herod.")   # refusing an answerable case


def test_keyword_pass_refusal_cases():
    assert llm_eval.keyword_pass(REFUSE, "I don't have enough information in my knowledge base to answer that.")
    assert llm_eval.keyword_pass(REFUSE, "The exact percentage is not specified in the context.")
    assert not llm_eval.keyword_pass(REFUSE, "It is 42 percent.")


# --- judge --------------------------------------------------------------------------------------------
def test_judge_builds_prompt_with_context_reference_and_answer(monkeypatch):
    seen = {}

    def fake(prompt, schema, name):
        seen.update(prompt=prompt, name=name, schema=schema)
        return {"relevance": 5, "accuracy": 4, "groundedness": 5, "explanation": "ok"}

    monkeypatch.setattr(llm_eval, "get_structured", fake)
    result = {"answer": "Herod.", "retrieved_chunks": [{"doc_id": 28, "chunk_id": 0, "text": "Caesarea was built by King Herod."}]}
    scores = llm_eval.judge(CASE, result)
    assert scores["accuracy"] == 4 and seen["name"] == "judge"
    assert "Caesarea was built by King Herod." in seen["prompt"] and "Herod" in seen["prompt"] and "ANSWER:\nHerod." in seen["prompt"]
    assert set(seen["schema"]["required"]) == {"relevance", "accuracy", "groundedness", "explanation"}


def test_judge_handles_no_retrieved_context(monkeypatch):
    seen = {}
    monkeypatch.setattr(llm_eval, "get_structured", lambda p, s, n: seen.update(prompt=p) or
                        {"relevance": 5, "accuracy": 5, "groundedness": 5, "explanation": "refusal"})
    llm_eval.judge(REFUSE, {"answer": "I don't have enough information.", "retrieved_chunks": []})
    assert "(none)" in seen["prompt"] and "must refuse" in seen["prompt"]


# --- aggregation ----------------------------------------------------------------------------------------
def _row(cat, rel, acc, grd, kw, passed):
    return {"category": cat, "relevance": rel, "accuracy": acc, "groundedness": grd, "keyword_pass": kw,
            "passed": passed, "latency_ms": 100.0}


def test_summarize_means_rates_and_agreement():
    rows = [_row("fact", 5, 5, 5, True, True), _row("fact", 5, 2, 5, False, False), _row("trap", 5, 3, 5, True, False)]
    s = llm_eval.summarize(rows, "x", "v1")
    assert s["pass_rate"] == pytest.approx(0.333, abs=1e-3) and s["accuracy"] == pytest.approx(3.33, abs=0.01)
    assert s["keyword_pass_rate"] == pytest.approx(0.667, abs=1e-3)
    assert s["judge_keyword_agreement"] == pytest.approx(0.667, abs=1e-3)      # rows 1 and 2 agree, row 3 does not
    assert s["by_category"] == {"fact": 0.5, "trap": 0.0}


def test_pass_requires_all_three_scores_at_threshold():
    assert min(5, 4, 4) >= llm_eval.PASS_THRESHOLD and not (min(5, 3, 5) >= llm_eval.PASS_THRESHOLD)


def test_dataset_is_well_formed():
    cases = json.loads((llm_eval.EVAL_DIR / "llm_eval_set.json").read_text(encoding="utf8"))
    assert len(cases) >= 30 and len({c["id"] for c in cases}) == len(cases)
    cats = {c["category"] for c in cases}
    assert {"fact", "comparison", "out_of_domain", "unanswerable_in_domain", "adversarial", "partial",
            "multi_hop", "numeric", "trap_specific_number"} <= cats
    for c in cases:
        assert c["expected_behavior"] and (c["should_refuse"] or c["key_facts"]), c["id"]


# --- prompt versions --------------------------------------------------------------------------------------
def test_prompt_versions_render_differently_and_switch():
    prompts.set_prompt_version("v1")
    v1 = prompts.render_rag_prompt("CTX", "q?")
    prompts.set_prompt_version("v2")
    v2 = prompts.render_rag_prompt("CTX", "q?")
    assert v1 != v2 and "Never add outside knowledge" in v2 and "CTX" in v1 and "CTX" in v2
    assert prompts.NO_CONTEXT_ANSWER in v1 and prompts.NO_CONTEXT_ANSWER in v2   # refusal sentence is shared


def test_unknown_prompt_version_rejected():
    with pytest.raises(ValueError):
        prompts.set_prompt_version("v99")
