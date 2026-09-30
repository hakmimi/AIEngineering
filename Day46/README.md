# Day 46 – Monitoring Report and Dashboard

## Goal

Turn the data the system already records into **operational insight**: how fast, how expensive, how routed, and is anything wrong – as a Markdown report, threshold alerts and an optional Streamlit dashboard.

```text
Audit records / Simulation results → Metrics module → Summary report / Dashboard → Operational insight
```

## What changed (vs Day 45)

| File | Change |
|---|---|
| `metrics.py` (new) | `load_audit_frame()` (audit DBs → one pandas row per decision), `summarize()` (latency percentiles, actions/routes, LLM status, fast-path share, cost and tokens, rates, per-route table, slowest / most expensive), `check_alerts()` (7 thresholds + guard overrides), `markdown_report()` |
| `scripts/metrics_report.py` (new) | `python -m scripts.metrics_report <audit.db> --label run2` → Markdown + JSON |
| `dashboard.py` (new) | Streamlit page (KPI tiles, alerts, decision/route charts, latency by route and over time, cost by LLM status, slowest decisions, reason codes); a thin view over `metrics.py` |
| `requirements-dashboard.txt` (new) | `streamlit` is optional |
| `data/simulation/run2*.{json,csv,db,md}` (new) | a fresh 100-event simulation with its own audit database, the input of this day's report |
| `tests/test_metrics.py` (new) | 23 tests incl. the dashboard rendered headlessly with Streamlit's `AppTest` → 419 in total |

## How it was done (steps 1–10)

1. **Load logs / simulation results** – from the audit table (it already stores latency, usage, route, tools, guard notes per decision, so no separate metrics pipeline is needed at this scale).
2–3. **Average and p95 latency** – plus p50, p90, p99, max; split *with LLM vs without*.
4. **Route distribution** – and actions, LLM status, top reason codes, fast-path share.
5. **Token/cost usage** – totals, per decision, per 1,000 decisions, per route, most expensive decisions.
6. **Slow cases** – top 5 by latency.
7. **Metrics report table** – `markdown_report()`.
8. **Streamlit page** – verified by running it headlessly (`AppTest`: no exceptions, five KPI tiles, database switch works).
9–10. **Findings and monitoring improvements** – below.

## What should be monitored (definitions)

| Signal | Why | Alert (default) |
|---|---|---|
| p95 latency | user-visible tail; dominated by the LLM | > 4,000 ms (warning) |
| LLM unavailable rate | the AI layer is down – decisions still work but lose explanations | > 5 % (**critical**) |
| LLM rejected-output rate | validation rejecting model text (grounding, length) → prompt/model drift | > 10 % (warning) |
| Tool failure rate | a data lookup is broken → cases fall to manual review | > 1 % (**critical**) |
| Manual-review / decline rate | staffing of the review queue; sudden change = traffic or rules change | > 25 % / > 15 % (warning) |
| Average cost per decision | budget | > $0.001 (warning) |
| Guard overrides | the constraint guard corrected a decision = an upstream bug | any (**critical**) |

## Findings on the 100-event simulation (`run2`)

| | Value |
|---|---|
| Latency avg / p50 / p95 / p99 / max | 1,232 / 1,698 / **2,804** / 3,486 / 3,912 ms |
| With LLM vs without | **2,082 ms vs 8.5 ms** |
| Decisions | route 81 · manual review 16 · decline 3 |
| Routes | normal 95 · fallback 5 |
| LLM status | reviewed 59 · fast path 32 · skipped (policy/fallback/tool) 9 |
| Cost | $0.0385 total · **$0.000385 per decision ($0.385 per 1,000)** · $0.00065 per LLM-reviewed decision |
| Tokens | 66,787 in / 7,383 out |
| Alerts | **none** (p95 2.8 s < 4 s; no LLM failures, tool failures or guard overrides; manual-review rate 16 %) |

Observations
- **Latency is bimodal**: rule-only paths take ≈ 8 ms, LLM-reviewed ones ≈ 2 s; the slowest five (2.8–3.9 s) are all LLM calls.
- **Cost is dominated by input tokens**: the priciest decisions send ≈ 1,270 input tokens (tool trace + policy list + transaction) for a ≈ 30-token answer. Trimming the prompt (e.g. compact tool results, policy ids instead of full text) is the cheapest lever – a candidate for a measured prompt experiment.
- **Reason codes**: `LOW_RISK` 69, `MEDIUM_RISK` 12, then the safety mechanisms (`AMOUNT_ANOMALY` 5, `INCONSISTENT_PROFILE` 4, `POLICY_BLOCK` 4, `NEW_CUSTOMER_HIGH_AMOUNT` 3, `CARD_TESTING_PATTERN` 2) – exactly the injected scenario mix, which is a useful sanity check.

## Monitoring improvements (next steps)

1. Export the same metrics as Prometheus/OpenTelemetry counters and histograms and alert from there (this module defines *what* to measure; the audit table is a fine store at this scale but not a time-series database).
2. Windowed alerts (last 5 minutes) instead of whole-database summaries; alert on *changes* against a baseline rather than fixed limits.
3. Add the **evaluation pass rate** as a scheduled metric (run the 45 cases nightly and chart it) so quality regressions show up like latency ones.
4. Add queue metrics (depth, wait time, worker utilisation) from Day 45's job table.
5. Track the *outcome* (chargebacks, review decisions) once real feedback exists – the only way to measure precision of declines/reviews.

## Run & test

```bash
cd Day46
python -m scripts.metrics_report data/simulation/run2_audit.db --label run2
pip install -r requirements-dashboard.txt
streamlit run dashboard.py
python -m pytest                                  # 419 offline tests
```
