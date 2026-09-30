# Day 48 - Simulation run + Week 3 consolidated report

## Goal
Prove the finished decision agent on fresh traffic (100 events, seed 11, real LLM, real HTTP server), and consolidate what
Week 3 (Days 36-47) delivered into one honest report.

## What changed
No production code changed. Added: this report, `data/simulation/week3*.{json,csv,md}` and `week3_audit.db` (the audit trail of the run).
The code is Day 47 (agent version v3), test suite 454 passing.

## How it was done
```
python -m scripts.simulate --label week3 --n 100 --seed 11 --spawn      # starts uvicorn, sends 100 events one by one
python -m scripts.analyze_simulation week3                             # scenario checks
python -m scripts.metrics_report --label week3 data/simulation/week3_audit.db
```
The mix is realistic routine traffic plus injected scenarios (policy violations, edge cases, card testing, anomalous amounts).

## Results
| Measure | Value |
|---|---|
| Events / failures | 100 / 0 (audit row for 100%) |
| Latency avg / p50 / p95 / max | 1143 / 1547 / 2546 / 3507 ms |
| With LLM vs without | 1.9 s vs 7.7 ms |
| LLM reviewed / fast path / rules-only skip | 59% / 25% / 16% |
| Cost | $0.0385 total, $0.000385 per decision (~$0.39 per 1,000) |
| Decisions | route 75, manual_review 17, decline 8 |
| Guard overrides | 0 |
| Injected scenarios handled as expected | policy_violation 3/3, edge_case 8/8, card_testing 5/5, anomalous_amount 1/1 |

Compared with the Day 41 run (p95 ~2.8 s, ~$0.00039/decision, fast path ~32% of realistic traffic): same cost, p95 slightly better, fast-path share
lower here (25%) because this seed drew more new-customer/medium-risk events.

## Week 3 in one page
| Day | Delivered | Evidence |
|---|---|---|
| 36-37 | Eval set with error direction; failures grouped | 64.5% baseline vs 87.1% AI on 31 cases |
| 38-40 | Fixes (patterns, policy, uncertainty route), agent version tag | 100% at v2/v3, 0 unsafe errors |
| 41 | First simulation | p95 2.8 s, $0.00039/decision |
| 42 | Architecture + evaluation docs | `docs/` |
| 43 | Fast path | ~32% LLM skipped, identical decisions |
| 44 | Async graph + warm-up | 22.9 vs 14.6 req/s at concurrency 100 |
| 45 | Job queue | fast-job wait 0.16 s vs 7.6 s (16 vs 4 workers) |
| 46 | Metrics + dashboard | alerts, Markdown report |
| 47 | Config layering + modes | graph 100% / 0 unsafe vs baseline 75.6% / 10 unsafe |

## Honest limits
- 100 events is a sample: p95 is estimated from ~5 slow calls; the tail beyond p95 is not established.
- Latency is dominated by one LLM call (about 1.9 s); the LLM changed 0 of 45 eval decisions - its value is explanations, not decisions.
- The traffic is synthetic; approval rates and fraud patterns are not real-world.
- Single process, SQLite, in-memory queue: no multi-instance guarantees.
