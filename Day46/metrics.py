"""Operational metrics from the audit table: what is the system doing, how fast, at what cost, and is anything wrong?

    audit records --> load_audit_frame() --> summarize() --> check_alerts() --> report / dashboard

The audit table already stores, per decision, everything a monitor needs (latency, route, action, LLM status, tokens and cost, tool
outcomes, guard overrides), so no separate metrics pipeline is required at this scale. For a real deployment the same numbers would
be exported as Prometheus/OpenTelemetry metrics; the definitions here are the part worth keeping.
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

# alert thresholds (illustrative; tune with real traffic)
DEFAULT_THRESHOLDS = {"p95_latency_ms": 4000, "llm_unavailable_rate": 0.05, "llm_rejected_rate": 0.10, "tool_failure_rate": 0.01,
                      "manual_review_rate": 0.25, "decline_rate": 0.15, "avg_cost_usd": 0.001}


def load_audit_frame(*db_paths: Path | str) -> pd.DataFrame:
    """One row per decision, flattened from the audit records of one or more databases (missing/empty databases are skipped)."""
    rows = []
    for path in db_paths:
        if not Path(path).exists():
            continue
        with closing(sqlite3.connect(path)) as db:
            try:
                records = [json.loads(r[0]) for r in db.execute("SELECT record FROM audit")]
            except sqlite3.OperationalError:
                continue
        for r in records:
            usage = r.get("usage", {})
            rows.append({
                "decision_id": r["decision_id"], "created_at": r["created_at"], "transaction_id": r["transaction_id"],
                "route": r["route"], "action": r["final_action"], "baseline_action": r["baseline_action"], "changed_by_ai": r["changed_by_ai"],
                "fast_path": r.get("fast_path"), "llm_status": r["llm"]["status"], "risk_score": r["risk_score"],
                "reason_code": r["reason_codes"][0] if r["reason_codes"] else None, "latency_ms": r["latency_ms"],
                "llm_calls": usage.get("llm_calls", 0), "input_tokens": usage.get("llm_input_tokens", 0),
                "output_tokens": usage.get("llm_output_tokens", 0), "cost_usd": usage.get("estimated_cost_usd", 0.0),
                "tools": len(r["tools_used"]), "tool_failures": sum(not t["ok"] for t in r["tools_used"]),
                "guard_override": any("constraint guard override" in n for n in r["technical_notes"]),
                "policy_block": "POLICY_BLOCK" in r["reason_codes"], "amount": r["input_summary"].get("amount"),
                "currency": r["input_summary"].get("currency"), "country": r["input_summary"].get("country"),
                "customer_type": r["input_summary"].get("customer_type")})
    df = pd.DataFrame(rows)
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"])
        df = df.sort_values("created_at").reset_index(drop=True)
    return df


def summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"decisions": 0}
    lat = df["latency_ms"]
    with_llm = df[df["llm_calls"] > 0]
    n = len(df)
    return {
        "decisions": n,
        "period": {"from": df["created_at"].min().isoformat(), "to": df["created_at"].max().isoformat()},
        "latency_ms": {"avg": round(lat.mean(), 1), "p50": round(lat.quantile(0.5), 1), "p90": round(lat.quantile(0.9), 1),
                       "p95": round(lat.quantile(0.95), 1), "p99": round(lat.quantile(0.99), 1), "max": round(lat.max(), 1)},
        "latency_with_llm_avg": round(with_llm["latency_ms"].mean(), 1) if len(with_llm) else None,
        "latency_without_llm_avg": round(df[df["llm_calls"] == 0]["latency_ms"].mean(), 1) if (df["llm_calls"] == 0).any() else None,
        "actions": df["action"].value_counts().to_dict(), "routes": df["route"].value_counts().to_dict(),
        "llm_status": df["llm_status"].value_counts().to_dict(), "top_reason_codes": df["reason_code"].value_counts().head(10).to_dict(),
        "fast_path_share": round(df["fast_path"].notna().mean(), 3), "changed_by_ai": int(df["changed_by_ai"].sum()),
        "cost": {"total_usd": round(df["cost_usd"].sum(), 5), "avg_usd": round(df["cost_usd"].mean(), 6),
                 "per_1000_usd": round(df["cost_usd"].mean() * 1000, 3), "input_tokens": int(df["input_tokens"].sum()),
                 "output_tokens": int(df["output_tokens"].sum()),
                 "avg_usd_llm_reviewed": round(with_llm["cost_usd"].mean(), 6) if len(with_llm) else None},
        "rates": {"llm_unavailable": round((df["llm_status"] == "unavailable").mean(), 4),
                  "llm_rejected": round((df["llm_status"] == "rejected_output").mean(), 4),
                  "tool_failure": round((df["tool_failures"] > 0).mean(), 4), "manual_review": round((df["action"] == "manual_review").mean(), 4),
                  "decline": round((df["action"] == "decline").mean(), 4), "policy_block": round(df["policy_block"].mean(), 4)},
        "guard_overrides": int(df["guard_override"].sum()),
        "by_route": {route: {"n": int(len(g)), "avg_ms": round(g["latency_ms"].mean(), 1), "p95_ms": round(g["latency_ms"].quantile(0.95), 1),
                             "avg_cost_usd": round(g["cost_usd"].mean(), 6)} for route, g in df.groupby("route")},
        "slowest": df.nlargest(5, "latency_ms")[["decision_id", "transaction_id", "latency_ms", "route", "action", "llm_status"]].to_dict("records"),
        "most_expensive": df.nlargest(5, "cost_usd")[["decision_id", "transaction_id", "cost_usd", "input_tokens", "route", "action"]].to_dict("records"),
    }


def check_alerts(summary: dict, thresholds: dict | None = None) -> list[dict]:
    """Threshold checks over a summary. Each alert says what crossed which limit; an empty list means 'nothing to look at'."""
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    if summary.get("decisions", 0) == 0:
        return [{"metric": "decisions", "value": 0, "limit": ">0", "severity": "warning", "message": "no decisions recorded"}]
    checks = [
        ("p95_latency_ms", summary["latency_ms"]["p95"], "p95 latency above the limit", "warning"),
        ("llm_unavailable_rate", summary["rates"]["llm_unavailable"], "the LLM was unavailable too often", "critical"),
        ("llm_rejected_rate", summary["rates"]["llm_rejected"], "too many LLM outputs were rejected by validation", "warning"),
        ("tool_failure_rate", summary["rates"]["tool_failure"], "tool lookups are failing", "critical"),
        ("manual_review_rate", summary["rates"]["manual_review"], "the manual-review queue is growing", "warning"),
        ("decline_rate", summary["rates"]["decline"], "unusually many declines", "warning"),
        ("avg_cost_usd", summary["cost"]["avg_usd"], "average cost per decision above budget", "warning"),
    ]
    alerts = [{"metric": m, "value": v, "limit": t[m], "severity": sev, "message": msg} for m, v, msg, sev in checks if v > t[m]]
    if summary["guard_overrides"] > 0:
        alerts.append({"metric": "guard_overrides", "value": summary["guard_overrides"], "limit": 0, "severity": "critical",
                       "message": "the constraint guard had to correct a decision - an upstream bug"})
    return alerts


def markdown_report(summary: dict, alerts: list[dict], title: str = "Operational metrics") -> str:
    if summary.get("decisions", 0) == 0:
        return f"# {title}\n\nNo decisions recorded.\n"
    lat, cost = summary["latency_ms"], summary["cost"]
    lines = [f"# {title}", "", f"{summary['decisions']} decisions ({summary['period']['from'][:19]} to {summary['period']['to'][:19]})", "",
             "| Metric | Value |", "|---|---|",
             f"| latency avg / p50 / p95 / p99 / max (ms) | {lat['avg']} / {lat['p50']} / {lat['p95']} / {lat['p99']} / {lat['max']} |",
             f"| latency with LLM vs without (ms) | {summary['latency_with_llm_avg']} vs {summary['latency_without_llm_avg']} |",
             f"| actions | {summary['actions']} |", f"| routes | {summary['routes']} |", f"| LLM status | {summary['llm_status']} |",
             f"| fast-path share | {summary['fast_path_share']:.0%} |",
             f"| cost total / per decision / per 1,000 (USD) | {cost['total_usd']} / {cost['avg_usd']} / {cost['per_1000_usd']} |",
             f"| tokens in / out | {cost['input_tokens']} / {cost['output_tokens']} |", f"| guard overrides | {summary['guard_overrides']} |", "",
             "## By route", "", "| route | n | avg ms | p95 ms | avg cost |", "|---|---:|---:|---:|---:|"]
    lines += [f"| {r} | {v['n']} | {v['avg_ms']} | {v['p95_ms']} | {v['avg_cost_usd']} |" for r, v in summary["by_route"].items()]
    lines += ["", "## Top reason codes", ""] + [f"- {k}: {v}" for k, v in summary["top_reason_codes"].items()]
    lines += ["", "## Slowest decisions", ""] + [f"- {s['decision_id']} ({s['transaction_id']}): {s['latency_ms']} ms, {s['route']}/{s['action']}, llm={s['llm_status']}" for s in summary["slowest"]]
    lines += ["", "## Most expensive decisions", ""] + [f"- {s['decision_id']} ({s['transaction_id']}): ${s['cost_usd']}, {s['input_tokens']} input tokens" for s in summary["most_expensive"]]
    lines += ["", "## Alerts", ""] + ([f"- **{a['severity']}** {a['metric']} = {a['value']} (limit {a['limit']}): {a['message']}" for a in alerts] or ["- none"])
    return "\n".join(lines) + "\n"
