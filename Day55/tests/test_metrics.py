"""Day 46: metrics from audit records - loading, summary maths, alerts, report, and the Streamlit page (AppTest)."""
from datetime import datetime, timedelta, timezone

import pytest

from audit import AuditRecord, AuditStore
from metrics import DEFAULT_THRESHOLDS, check_alerts, load_audit_frame, markdown_report, summarize

T0 = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)


def record(i, *, route="normal", action="route", llm="ok", latency=1500.0, cost=0.0005, llm_calls=1, fast=None, reason="LOW_RISK",
           tools=None, notes=None, changed=False, tokens=250):
    return AuditRecord(
        decision_id=f"dec_{i:04d}", created_at=(T0 + timedelta(seconds=i)).isoformat(timespec="milliseconds"), request_id=f"r{i}", agent_version="v3",
        transaction_id=f"t-{i}", input_summary={"amount": 100.0, "currency": "USD", "country": "US", "customer_type": "returning"},
        route=route, route_reason=None, graph_trace=["input"], tools_used=tools if tools is not None else [{"tool": "risk_lookup", "ok": True, "ms": 0.1, "arguments": "{}"}],
        risk_score=0.1, risk_components={}, baseline_action=action, baseline_provider=None, final_action=action, final_provider=None,
        reason_codes=[reason], changed_by_ai=changed, fast_path=fast, llm={"status": llm}, business_explanation="x", technical_notes=notes or [],
        usage={"llm_calls": llm_calls, "llm_input_tokens": tokens if llm_calls else 0, "llm_output_tokens": 30 if llm_calls else 0,
               "estimated_cost_usd": cost if llm_calls else 0.0}, latency_ms=latency)


@pytest.fixture
def db(tmp_path):
    def build(records, name="audit.db"):
        store = AuditStore(tmp_path / name)
        for r in records:
            store.save(r)
        return tmp_path / name
    return build


# --- loading -----------------------------------------------------------------------------------------------------------------------
def test_frame_has_one_row_per_decision_with_flattened_fields(db):
    path = db([record(1), record(2, action="decline", reason="HIGH_RISK", route="normal", llm="skipped_fast_path", llm_calls=0, fast="clear_decline")])
    df = load_audit_frame(path)
    assert len(df) == 2 and list(df["decision_id"]) == ["dec_0001", "dec_0002"]
    row = df.iloc[1]
    assert row["action"] == "decline" and row["reason_code"] == "HIGH_RISK" and row["fast_path"] == "clear_decline" and row["llm_calls"] == 0
    assert row["amount"] == 100.0 and row["country"] == "US" and str(df["created_at"].dtype).startswith("datetime64")


def test_missing_or_empty_databases_are_skipped(tmp_path, db):
    assert load_audit_frame(tmp_path / "nope.db").empty
    empty = tmp_path / "empty.db"
    import sqlite3
    sqlite3.connect(empty).close()                                   # a database without the audit table
    assert load_audit_frame(empty).empty
    assert len(load_audit_frame(tmp_path / "nope.db", db([record(1)]))) == 1


def test_several_databases_are_combined_and_sorted_by_time(db):
    a, b = db([record(5)], "a.db"), db([record(1), record(9)], "b.db")
    assert list(load_audit_frame(a, b)["decision_id"]) == ["dec_0001", "dec_0005", "dec_0009"]


def test_guard_overrides_tool_failures_and_policy_blocks_are_detected(db):
    df = load_audit_frame(db([
        record(1, notes=["constraint guard override: policy: P1"]),
        record(2, tools=[{"tool": "risk_lookup", "ok": False, "ms": 1, "arguments": "{}"}]),
        record(3, reason="POLICY_BLOCK", action="decline")]))
    assert list(df["guard_override"]) == [True, False, False] and list(df["tool_failures"]) == [0, 1, 0] and list(df["policy_block"]) == [False, False, True]


# --- summary maths -----------------------------------------------------------------------------------------------------------------------
def test_latency_percentiles_and_llm_split(db):
    records = [record(i, latency=100.0 * i, llm_calls=1 if i <= 5 else 0, llm="ok" if i <= 5 else "skipped_fast_path") for i in range(1, 11)]
    s = summarize(load_audit_frame(db(records)))
    assert s["decisions"] == 10 and s["latency_ms"]["max"] == 1000 and s["latency_ms"]["avg"] == 550 and s["latency_ms"]["p50"] == pytest.approx(550)
    assert s["latency_with_llm_avg"] == 300 and s["latency_without_llm_avg"] == 800


def test_cost_tokens_and_per_1000(db):
    s = summarize(load_audit_frame(db([record(1, cost=0.001), record(2, cost=0.003), record(3, llm_calls=0)])))
    assert s["cost"]["total_usd"] == 0.004 and s["cost"]["avg_usd"] == pytest.approx(0.001333, abs=1e-6) and s["cost"]["input_tokens"] == 500
    assert s["cost"]["avg_usd_llm_reviewed"] == 0.002 and s["cost"]["per_1000_usd"] == pytest.approx(1.333, abs=1e-3)


def test_distributions_rates_and_shares(db):
    records = [record(1), record(2, action="manual_review", reason="MEDIUM_RISK"), record(3, action="decline", reason="HIGH_RISK"),
               record(4, llm="unavailable", llm_calls=0), record(5, fast="routine_low_risk", llm="skipped_fast_path", llm_calls=0),
               record(6, route="fallback", action="manual_review", reason="UNKNOWN_COUNTRY", llm="skipped", llm_calls=0)]
    s = summarize(load_audit_frame(db(records)))
    assert s["actions"] == {"route": 3, "manual_review": 2, "decline": 1} and s["routes"] == {"normal": 5, "fallback": 1}
    assert s["rates"]["llm_unavailable"] == pytest.approx(1 / 6, abs=1e-3) and s["rates"]["manual_review"] == pytest.approx(2 / 6, abs=1e-3)
    assert s["fast_path_share"] == pytest.approx(1 / 6, abs=1e-3) and s["top_reason_codes"]["LOW_RISK"] == 3


def test_by_route_breakdown_and_rankings(db):
    records = [record(1, route="normal", latency=100, cost=0.001), record(2, route="normal", latency=300, cost=0.003),
               record(3, route="fallback", latency=5, llm_calls=0)]
    s = summarize(load_audit_frame(db(records)))
    assert s["by_route"]["normal"]["n"] == 2 and s["by_route"]["normal"]["avg_ms"] == 200 and s["by_route"]["fallback"]["avg_cost_usd"] == 0
    assert s["slowest"][0]["decision_id"] == "dec_0002" and s["most_expensive"][0]["decision_id"] == "dec_0002"


def test_empty_frame_summary():
    import pandas as pd
    assert summarize(pd.DataFrame()) == {"decisions": 0}


# --- alerts ------------------------------------------------------------------------------------------------------------------------------
def test_healthy_traffic_raises_no_alerts(db):
    assert check_alerts(summarize(load_audit_frame(db([record(i) for i in range(1, 21)])))) == []


@pytest.mark.parametrize("build,metric,severity", [
    (lambda: [record(i, latency=9000.0) for i in range(1, 11)], "p95_latency_ms", "warning"),
    (lambda: [record(i, llm="unavailable", llm_calls=0) for i in range(1, 11)], "llm_unavailable_rate", "critical"),
    (lambda: [record(i, llm="rejected_output") for i in range(1, 11)], "llm_rejected_rate", "warning"),
    (lambda: [record(i, tools=[{"tool": "x", "ok": False, "ms": 1, "arguments": ""}]) for i in range(1, 11)], "tool_failure_rate", "critical"),
    (lambda: [record(i, action="manual_review") for i in range(1, 11)], "manual_review_rate", "warning"),
    (lambda: [record(i, action="decline", reason="HIGH_RISK") for i in range(1, 11)], "decline_rate", "warning"),
    (lambda: [record(i, cost=0.01) for i in range(1, 11)], "avg_cost_usd", "warning"),
    (lambda: [record(1, notes=["constraint guard override: x"])] + [record(i) for i in range(2, 11)], "guard_overrides", "critical"),
])
def test_each_alert_fires_for_its_own_condition(db, build, metric, severity):
    alerts = check_alerts(summarize(load_audit_frame(db(build()))))
    fired = {a["metric"]: a for a in alerts}
    assert metric in fired and fired[metric]["severity"] == severity and fired[metric]["message"]


def test_thresholds_can_be_overridden_and_no_data_is_itself_an_alert(db):
    s = summarize(load_audit_frame(db([record(i, latency=2000.0) for i in range(1, 6)])))
    assert not check_alerts(s) and check_alerts(s, {"p95_latency_ms": 1000})[0]["metric"] == "p95_latency_ms"
    assert check_alerts({"decisions": 0})[0]["metric"] == "decisions" and set(DEFAULT_THRESHOLDS) >= {"p95_latency_ms", "avg_cost_usd"}


# --- report ---------------------------------------------------------------------------------------------------------------------------------
def test_markdown_report_contains_the_key_sections(db):
    s = summarize(load_audit_frame(db([record(i, latency=100.0 * i) for i in range(1, 9)])))
    text = markdown_report(s, check_alerts(s), title="T")
    for expected in ("# T", "latency avg / p50 / p95", "## By route", "## Top reason codes", "## Slowest decisions", "## Most expensive", "## Alerts", "- none"):
        assert expected in text
    assert "No decisions recorded" in markdown_report({"decisions": 0}, [])


def test_report_cli_writes_markdown_and_json(tmp_path, db, monkeypatch, capsys):
    import json
    import sys

    from scripts import metrics_report
    path = db([record(i) for i in range(1, 6)])
    monkeypatch.setattr(sys, "argv", ["metrics_report", str(path), "--label", "pytest_tmp"])
    metrics_report.main()
    out = metrics_report.settings.data_dir / "simulation"
    data = json.loads((out / "pytest_tmp_metrics.json").read_text(encoding="utf8"))
    assert data["summary"]["decisions"] == 5 and data["alerts"] == []
    (out / "pytest_tmp_metrics.json").unlink()
    (out / "pytest_tmp_metrics.md").unlink()
    assert "Operational metrics - pytest_tmp" in capsys.readouterr().out


# --- dashboard ------------------------------------------------------------------------------------------------------------------------------
def test_dashboard_renders_without_errors_on_real_data(db, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("DASHBOARD_DB", str(db([record(i, latency=100.0 * i) for i in range(1, 30)])))
    at = AppTest.from_file("dashboard.py", default_timeout=30).run()
    assert not at.exception, at.exception
    assert len(at.metric) == 5 and at.title[0].value.startswith("Payment routing agent")


def test_dashboard_shows_a_warning_when_the_database_has_no_decisions(db, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("DASHBOARD_DB", str(db([])))
    at = AppTest.from_file("dashboard.py", default_timeout=30).run()
    assert not at.exception and len(at.warning) == 1
