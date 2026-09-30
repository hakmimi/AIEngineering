# Day 43 – Traffic Simulator

## Goal

Replay realistic traffic against the running decision API, record route / decision / latency / cost per request, and learn how the system behaves **as a service** rather than one test case at a time – including whether the injected bad events are handled correctly at the rate they would occur.

```text
Event Generator → API Client → Decision API → Results Store → Analysis
```

## What changed (vs Day 42)

| File | Change |
|---|---|
| `traffic.py` (new) | `build_events(n, seed, mix)`: a labelled mix of **routine** traffic (from the synthetic-world generator) and injected scenarios: card testing, anomalous amounts, policy violations, edge cases; the scenario label stays client-side |
| `scripts/simulate.py` (new) | HTTP client: waits for `/health`, sends events one by one with an `X-Request-ID` (`sim-<seed>-<i>`), records status, decision, route, LLM status, fast path, blocked policies, server and wall latency, cost, `decision_id`; `--spawn` starts an isolated local server; writes JSON + CSV |
| `scripts/analyze_simulation.py` (new) | latency (avg / p50 / p95 / max, server and client), decision + route distribution, LLM and fast-path share, cost, LLM-vs-no-LLM latency, slowest requests, and **per-scenario expectation checks** |
| `config.py` | `AUDIT_DB_PATH` environment override (each simulation gets its own audit database) |
| `data/simulation/run1.*` | the stored run (events, analysis, Markdown report) |
| `tests/test_simulation_traffic.py` (new) | 16 offline tests (fake HTTP transport) → 347 in total |

## How it was done (steps 1–10)

1. **Scenarios** – default mix: 84 % routine, 4 % card testing, 3 % anomalous amount, 5 % policy violations (sanctions / wallet over limit / gaming by bank transfer), 4 % edge cases (unknown country, VIP or returning customer with a days-old account).
2. **100 events** – seeded (`--seed 7`), all valid `Transaction`s with unique ids (tested on 300 events).
3–4. **API client / send one by one** – `python -m scripts.simulate --label run1 --n 100 --seed 7 --spawn`.
5. **Capture response, route, latency** and 6. **store results** – one row per event, JSON + CSV.
7–9. **Analyse** average latency, route distribution, slow cases – below. 10. **Document** – this file.

## Results (run1: 100 events, sequential, live LLM)

| Measure | Value |
|---|---|
| Requests succeeded / failed | 100 / 0 (audit recorded for 100 %) |
| Server latency avg / p50 / p95 / max | **1,257 ms** / 1,628 ms / **2,725 ms** / 4,609 ms |
| Latency with an LLM review vs without | **1,930 ms vs 8.4 ms** |
| Decisions | route 81 · manual review 14 · decline 5 |
| Routes | normal 96 · fallback 3 · uncertain 1 |
| LLM status | reviewed 65 · fast path 25 · skipped (policy / fallback / tool) 10 |
| Cost | $0.043 total · **$0.00043 per decision** (≈ $0.43 per 1,000 decisions) |
| Wall-clock for 100 sequential requests | 133 s (≈ 0.75 requests/s) |

Slowest requests: 4.6 s, 3.5 s, 3.0 s, 3.0 s, 2.7 s – **all LLM-reviewed**; nothing without an LLM took more than a few milliseconds.

### Were the injected scenarios handled correctly?

| Scenario | Events | Handled as expected |
|---|---:|---:|
| policy violations | 3 | 3 / 3 declined or reviewed with `POLICY_BLOCK` |
| edge cases | 3 | 3 / 3 manual review via fallback (or policy) |
| card testing | 5 | 5 / 5 manual review |
| anomalous amounts | 2 | 2 / 2 manual review |
| routine (87) | – | 81 routed, 4 reviewed, 2 declined by ordinary risk rules |

## What the simulation taught us

- **Throughput is limited by the LLM, not by our code**: a single worker handles ≈ 0.75 requests/s in sequence because two thirds of requests wait ≈ 2 s on the LLM. Fast-path and policy/fallback requests take milliseconds. That is exactly what Day 44's async work targets.
- **Real mix vs the evaluation set**: on realistic traffic only 4 of 100 requests used a safety route (3 fallback + 1 uncertain) and 25 % took the fast path (32 % predicted from the synthetic population – small-sample noise); the evaluation set is deliberately far more adversarial.
- **Tail latency** (p95 2.7 s, max 4.6 s) is one slow LLM call; there is no retry involved here, so it is provider variance – relevant for any SLA (an LLM timeout is 20 s by configuration).
- Routine traffic also produces reviews/declines (6 of 87, 7 %) purely from risk rules – the manual-review queue a real operation would have to staff.

## Caveats

100 events and one seed: percentages carry a few points of noise. The client and server ran on one machine (network latency ≈ 0). Injected scenarios are the author's model of what bad traffic looks like.

## Run & test

```bash
cd Day43
python -m scripts.simulate --label run2 --n 100 --seed 8 --spawn     # live, ~$0.04, ~2 minutes
python -m scripts.analyze_simulation run2
python -m pytest                                                     # 347 offline tests
```
