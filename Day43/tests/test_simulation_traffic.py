"""Day 43: traffic generation, the simulator client and the analysis - all offline (the server is replaced by a fake transport)."""
import csv
import json
from collections import Counter

import httpx
import pytest

from schemas import Transaction
from scripts import analyze_simulation, simulate
from traffic import DEFAULT_MIX, build_events


# --- traffic generator ------------------------------------------------------------------------------------------------------------
def test_every_generated_event_is_a_valid_transaction_with_a_unique_id():
    events = build_events(300, seed=1)
    ids = [e["event"]["transaction_id"] for e in events]
    assert len(ids) == len(set(ids)) == 300
    for item in events:
        Transaction(**item["event"])                        # raises if the simulator ever produces an invalid event


def test_same_seed_same_traffic_different_seed_different_traffic():
    assert build_events(50, seed=3) == build_events(50, seed=3)
    assert build_events(50, seed=3) != build_events(50, seed=4)


def test_scenario_mix_roughly_follows_the_configured_shares():
    counts = Counter(e["scenario"] for e in build_events(2000, seed=5))
    assert counts["routine"] / 2000 == pytest.approx(DEFAULT_MIX["routine"], abs=0.04)
    assert set(counts) == set(DEFAULT_MIX)


def test_hidden_truth_columns_never_reach_the_events():
    for item in build_events(100, seed=2):
        assert not {"simulated_risk_score", "is_fraud", "historical_provider", "approved_outcome", "scenario"} & set(item["event"])


def test_special_scenarios_contain_what_they_claim():
    events = build_events(1500, seed=9)
    by = {s: [e["event"] for e in events if e["scenario"] == s] for s in DEFAULT_MIX}
    assert all(e["customer_type"] == "new" and e["amount"] <= 5 and e["merchant_category"] in ("digital_goods", "gaming") for e in by["card_testing"])
    assert all(e["amount"] >= 4000 and e["merchant_category"] == "groceries" for e in by["anomalous_amount"])
    assert all(e["country"] in ("KP", "IR", "SY", "CU") or e["payment_method"] in ("wallet", "bank_transfer") for e in by["policy_violation"])
    assert all(e["country"] in ("ZZ", "XX", "QQ") or e["customer_type"] in ("vip", "returning") for e in by["edge_case"])


def test_custom_mix_and_invalid_n():
    assert {e["scenario"] for e in build_events(40, seed=1, mix={"routine": 1.0})} == {"routine"}
    with pytest.raises(ValueError):
        build_events(0)


# --- simulator client -------------------------------------------------------------------------------------------------------------------
def fake_server(handler):
    return httpx.MockTransport(handler)


def ok_body(action="route"):
    return {"decision": {"action": action, "selected_provider": "alpha_pay", "reason_codes": ["LOW_RISK"]}, "graph": {"route": "normal"},
            "llm_status": "ok", "fast_path": None, "blocked_by": [], "latency_ms": 12.5,
            "usage": {"llm_calls": 1, "estimated_cost_usd": 0.0005}, "decision_id": "dec_x", "audit_recorded": True}


def test_run_collects_one_row_per_event(monkeypatch):
    seen = []

    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        seen.append((request.headers["x-request-id"], json.loads(request.content)["transaction_id"]))
        return httpx.Response(200, json=ok_body())

    real = httpx.Client
    monkeypatch.setattr(simulate.httpx, "Client", lambda **kw: real(transport=fake_server(handler), **kw))
    rows = simulate.run("http://test", 10, seed=1)
    assert len(rows) == 10 and all(r["status"] == 200 and r["action"] == "route" and r["decision_id"] == "dec_x" for r in rows)
    assert seen[0][0] == "sim-1-0000" and len({s[1] for s in seen}) == 10                      # request ids are traceable per run


def test_run_records_http_and_server_errors_without_stopping(monkeypatch):
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        n = json.loads(request.content)["transaction_id"]
        if n.endswith("0"):
            raise httpx.ConnectError("boom")
        if n.endswith("1"):
            return httpx.Response(500, json={"detail": "Internal server error"})
        return httpx.Response(200, json=ok_body())

    real = httpx.Client
    monkeypatch.setattr(simulate.httpx, "Client", lambda **kw: real(transport=fake_server(handler), **kw))
    rows = simulate.run("http://test", 12, seed=1)
    assert len(rows) == 12
    assert {r["status"] for r in rows} == {0, 200, 500} and any(r.get("error") == "ConnectError" for r in rows)


def test_wait_until_healthy_gives_up(monkeypatch):
    client = httpx.Client(base_url="http://x", transport=fake_server(lambda r: httpx.Response(503)))
    monkeypatch.setattr(simulate.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        simulate.wait_until_healthy(client, seconds=0.05)


def test_save_writes_json_and_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(simulate, "OUT_DIR", tmp_path)
    rows = [{"i": 0, "scenario": "routine", "transaction_id": "a", "status": 200, "action": "route", "wall_ms": 5.0},
            {"i": 1, "scenario": "edge_case", "transaction_id": "b", "status": 0, "error": "ConnectError", "wall_ms": 1.0}]
    simulate.save("t", rows, {"label": "t"})
    assert json.loads((tmp_path / "t.json").read_text(encoding="utf8"))["rows"] == rows
    assert len(list(csv.DictReader((tmp_path / "t.csv").open(encoding="utf-8-sig")))) == 2


# --- analysis ----------------------------------------------------------------------------------------------------------------------------
def row(i, scenario, action, route="normal", llm=1, server_ms=100.0, reason="LOW_RISK", fast=None, status="ok", cost=0.0005):
    return {"i": i, "scenario": scenario, "transaction_id": f"s{i}", "status": 200, "action": action, "route": route, "llm_status": status,
            "fast_path": fast, "server_ms": server_ms, "wall_ms": server_ms + 5, "llm_calls": llm, "cost_usd": cost, "reason_codes": reason, "audit_recorded": True}


def test_percentile_and_basic_aggregation():
    assert analyze_simulation.percentile([1, 2, 3, 4, 100], 0.5) == 3 and analyze_simulation.percentile([], 0.5) == 0.0
    rows = [row(i, "routine", "route", server_ms=100.0 * (i + 1)) for i in range(10)]
    a = analyze_simulation.analyze(rows)
    assert a["events"] == a["succeeded"] == 10 and a["latency_ms"]["server_avg"] == 550 and a["latency_ms"]["server_max"] == 1000
    assert a["cost"]["total_usd"] == 0.005 and a["llm_reviewed_share"] == 1.0 and a["actions"] == {"route": 10}


def test_failed_requests_are_counted_and_excluded_from_latency():
    rows = [row(0, "routine", "route"), {"i": 1, "scenario": "routine", "transaction_id": "x", "status": 500, "wall_ms": 3.0}]
    a = analyze_simulation.analyze(rows)
    assert a["failed"] == 1 and a["succeeded"] == 1 and a["latency_ms"]["server_avg"] == 100


def test_llm_and_fast_path_shares_and_latency_split():
    rows = [row(0, "routine", "route", llm=1, server_ms=2000), row(1, "routine", "route", llm=0, server_ms=10, fast="routine_low_risk", status="skipped_fast_path")]
    a = analyze_simulation.analyze(rows)
    assert a["fast_path_share"] == 0.5 and a["llm_reviewed_share"] == 0.5
    assert a["latency_llm_vs_no_llm_ms"] == {"with_llm_avg": 2000, "without_llm_avg": 10}


def test_scenario_expectations_pass_and_fail_correctly():
    good = [row(0, "policy_violation", "decline", reason="POLICY_BLOCK"), row(1, "edge_case", "manual_review", route="fallback"),
            row(2, "card_testing", "manual_review"), row(3, "anomalous_amount", "manual_review")]
    checks = analyze_simulation.analyze(good)["scenario_checks"]
    assert all(c["as_expected"] == c["events"] for c in checks.values()) and set(checks) == set(analyze_simulation.EXPECTATIONS)
    bad = [row(0, "policy_violation", "route", reason="LOW_RISK"), row(1, "card_testing", "route")]
    checks = analyze_simulation.analyze(bad)["scenario_checks"]
    assert checks["policy_violation"]["failed"] == ["s0"] and checks["card_testing"]["failed"] == ["s1"]


def test_slowest_requests_are_ranked_and_report_renders():
    rows = [row(i, "routine", "route", server_ms=float(i)) for i in range(8)]
    a = analyze_simulation.analyze(rows)
    assert [s["id"] for s in a["slowest"]] == ["s7", "s6", "s5", "s4", "s3"]
    text = analyze_simulation.report("t", a)
    assert "# Simulation report - t" in text and "server latency" in text and "Slowest requests" in text


def test_stored_run1_meets_the_documented_expectations():
    data = json.loads((analyze_simulation.OUT_DIR / "run1.json").read_text(encoding="utf8"))
    a = analyze_simulation.analyze(data["rows"])
    assert a["events"] == 100 and a["failed"] == 0 and a["audit_recorded_share"] == 1.0
    assert all(c["as_expected"] == c["events"] for c in a["scenario_checks"].values())
