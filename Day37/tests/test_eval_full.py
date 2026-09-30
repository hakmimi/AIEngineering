"""Day 37: the comparison machinery - failure grouping, metrics, report, output files, dataset probes."""
import csv
import json

import pytest

from evaluation import Actual, CaseResult, load_cases
from schemas import Action
from scripts import eval_full


def result(case_id, category, passed, error=None, provider_ok=None, action="route", cost=0.0, latency=1.0, status=None, expl=10):
    actual = Actual(Action(action), None, "normal", ["LOW_RISK"], "text", latency_ms=latency, cost_usd=cost, llm_status=status)
    return CaseResult(case_id, category, actual, action_ok=error is None, provider_ok=provider_ok, route_ok=True, reasons_ok=True,
                      error_type=error, passed=passed, explanation_score={"total": expl, "passed": expl >= 8}, details=[])


def test_failure_groups_split_by_error_type_and_category():
    results = [result("a", "edge", False, "unsafe_error"), result("b", "edge", False, "unsafe_error"), result("c", "normal", False, "over_cautious"),
               result("d", "normal", False, provider_ok=False), result("e", "risky", False), result("f", "risky", True)]
    groups = eval_full.failure_groups(results)
    assert groups == {"unsafe_error [edge]": ["a", "b"], "over_cautious [normal]": ["c"], "wrong_provider [normal]": ["d"],
                      "wrong_route_or_reason [risky]": ["e"]}


def test_mode_metrics_aggregate_explanations_latency_cost_and_llm_status():
    m = eval_full.mode_metrics([result("a", "normal", True, cost=0.001, latency=100, status="ok", expl=10),
                                result("b", "normal", True, cost=0.003, latency=300, status="unavailable", expl=6)])
    assert m["explanation_avg_score"] == 8 and m["explanation_pass_rate"] == 0.5 and m["latency_p50_ms"] == 200 and m["latency_max_ms"] == 300
    assert m["total_cost_usd"] == pytest.approx(0.004) and m["llm_status"] == {"ok": 1, "unavailable": 1}


def test_report_contains_the_comparison_table_and_failures():
    summary = {"label": "t", "baseline": eval_full.mode_metrics([result("a", "edge", False, "unsafe_error")]),
               "ai": eval_full.mode_metrics([result("a", "edge", True)]), "decisions_differing": 1, "route_accuracy_gain": 0.0,
               "baseline_failures": {"unsafe_error [edge]": ["a"]}, "ai_failures": {},
               "lowest_ai_explanations": [{"score": 8, "case": "a", "text": "hello"}]}
    text = eval_full.report(summary)
    assert "| case pass rate | 0.0 | 1.0 |" in text and "unsafe_error [edge]" in text and "- a (8/10): hello" in text


def test_outputs_are_written_as_json_and_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_full, "EVAL_DIR", tmp_path)
    cases = load_cases(limit=2)
    base = [result(c.id, c.category, True) for c in cases]
    ai = [result(c.id, c.category, False, "unsafe_error") for c in cases]
    summary = eval_full.write_outputs("t", cases, base, ai)
    rows = list(csv.DictReader((tmp_path / "full_t.csv").open(encoding="utf-8-sig")))
    assert len(rows) == 2 and rows[0]["baseline_pass"] == "True" and rows[0]["ai_pass"] == "False" and rows[0]["ai_error"] == "unsafe_error"
    stored = json.loads((tmp_path / "full_t.json").read_text(encoding="utf8"))
    assert stored["summary"]["ai_failures"] == summary["ai_failures"] and len(stored["rows"]) == 2


def test_probe_cases_exist_and_do_not_constrain_the_route():
    probes = [c for c in load_cases() if c.category == "probe"]
    assert len(probes) >= 8 and all(c.expected.route is None for c in probes)


def test_probes_include_the_documented_blind_spots():
    ids = {c.id for c in load_cases()}
    assert {"p01_card_testing_digital", "p03_grocery_5000", "p04_four_chargebacks"} <= ids


def test_stored_v1_report_matches_the_documented_numbers():
    stored = json.loads((eval_full.EVAL_DIR / "full_v1.json").read_text(encoding="utf8"))["summary"]
    assert stored["baseline"]["cases"] == stored["ai"]["cases"] == len(load_cases())
    assert stored["ai"]["pass_rate"] > stored["baseline"]["pass_rate"] and stored["ai"]["errors"].get("unsafe_error", 0) < stored["baseline"]["errors"]["unsafe_error"]
