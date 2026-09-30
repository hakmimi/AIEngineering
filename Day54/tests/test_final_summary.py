"""The final summary is generated from stored evidence; these tests keep the evidence and the document honest."""
import json

from config import settings
from scripts.final_summary import build

EVAL = settings.data_dir / "eval"


def test_document_matches_the_stored_evidence():
    assert (settings.base_dir / "docs" / "FINAL_EVALUATION.md").read_text(encoding="utf8") == build(), "run: python -m scripts.final_summary"


def test_final_run_has_no_unsafe_errors_and_no_regression_against_the_previous_run():
    v3, v4 = (json.loads((EVAL / f"full_{v}.json").read_text(encoding="utf8")) for v in ("v3", "v4"))
    assert v4["summary"]["ai"]["errors"].get("unsafe_error", 0) == 0
    old = {r["case_id"]: r for r in v3["rows"]}
    regressed = [r["case_id"] for r in v4["rows"] if r["case_id"] in old and old[r["case_id"]]["ai_pass"] and not r["ai_pass"]]
    assert regressed == []


def test_every_evaluation_case_was_run_in_the_final_evaluation():
    from evaluation import load_cases
    assert {c.id for c in load_cases()} == {r["case_id"] for r in json.loads((EVAL / "full_v4.json").read_text(encoding="utf8"))["rows"]}


def test_mode_comparison_shows_only_the_graph_without_unsafe_errors():
    modes = json.loads((EVAL / "modes_final.json").read_text(encoding="utf8"))["modes"]
    assert modes["graph"]["errors"].get("unsafe_error", 0) == 0
    assert modes["baseline"]["errors"].get("unsafe_error", 0) > 0 and modes["ai"]["errors"].get("unsafe_error", 0) > 0


def test_the_document_states_its_limits():
    text = (settings.base_dir / "docs" / "FINAL_EVALUATION.md").read_text(encoding="utf8")
    assert "regression guard" in text and "synthetic" in text and "What this does not show" in text
