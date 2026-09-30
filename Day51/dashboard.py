"""Streamlit dashboard over the audit database (optional: `pip install -r requirements-dashboard.txt`).

    streamlit run dashboard.py

Everything shown comes from metrics.py - the dashboard is a thin view, so the numbers are the same as in the Markdown report.
"""
import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings  # noqa: E402
from metrics import DEFAULT_THRESHOLDS, check_alerts, load_audit_frame, summarize  # noqa: E402

st.set_page_config(page_title="Decision agent monitoring", layout="wide")
st.title("Payment routing agent - operational metrics")

default_db = Path(os.getenv("DASHBOARD_DB") or settings.audit_db_path)          # DASHBOARD_DB: open a specific database (tests, demos)
choices = sorted({str(default_db), *(str(p) for p in settings.data_dir.rglob("*audit*.db"))})
db = st.sidebar.selectbox("Audit database", choices, index=choices.index(str(default_db)))
p95_limit = st.sidebar.number_input("p95 latency alert (ms)", value=DEFAULT_THRESHOLDS["p95_latency_ms"], step=250)

df = load_audit_frame(db)
if df.empty:
    st.warning("No decisions recorded in this database yet.")
    st.stop()

summary = summarize(df)
alerts = check_alerts(summary, {"p95_latency_ms": p95_limit})

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Decisions", summary["decisions"])
c2.metric("Latency p50 (ms)", summary["latency_ms"]["p50"])
c3.metric("Latency p95 (ms)", summary["latency_ms"]["p95"])
c4.metric("Cost / 1,000 decisions (USD)", summary["cost"]["per_1000_usd"])
c5.metric("Fast-path share", f"{summary['fast_path_share']:.0%}")

if alerts:
    for a in alerts:
        (st.error if a["severity"] == "critical" else st.warning)(f"{a['metric']} = {a['value']} (limit {a['limit']}): {a['message']}")
else:
    st.success("No alerts")

left, right = st.columns(2)
left.subheader("Decisions")
left.bar_chart(df["action"].value_counts())
right.subheader("Routes")
right.bar_chart(df["route"].value_counts())

st.subheader("Latency by route (ms)")
st.dataframe(df.groupby("route")["latency_ms"].describe(percentiles=[0.5, 0.95]).round(1))

st.subheader("Latency over time")
st.line_chart(df.set_index("created_at")["latency_ms"])

st.subheader("Cost per decision")
st.bar_chart(df.groupby("llm_status")["cost_usd"].mean())

st.subheader("Slowest decisions")
st.dataframe(df.nlargest(10, "latency_ms")[["decision_id", "transaction_id", "latency_ms", "route", "action", "llm_status"]])
st.subheader("Top reason codes")
st.bar_chart(df["reason_code"].value_counts().head(10))
