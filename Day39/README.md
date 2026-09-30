# Day 39 – Latency, Cost and the Fast Path

## Goal

Measure what the AI layer costs (time and money) versus the rules alone, decide **when the LLM is worth using**, and cut the cost where it buys nothing: a **fast path** that skips the LLM when the rules' outcome is unambiguous.

```text
Eval Case → Decision Path → Latency / Cost Tracking → Results Table → Tradeoff Analysis
```

## What changed (vs Day 38)

| File | Change |
|---|---|
| `fast_path.py` (new) | `evaluate_fast_path(tx, baseline)` → fast or not, with a reason: **clear declines** and **routine low-risk routed payments** (risk < 0.15, established customer, no chargebacks, amount ≤ 3× typical) skip the LLM |
| `decision_graph.py` | new node `fast_explain` (template explanation, `llm_status="skipped_fast_path"`), conditional edge `after_baseline` used after both the rules node and the select node; `graph_done` log now carries `fast_path` and `latency_ms` |
| `ai_decision.py`, `main.py` | responses report `fast_path`; `/decision/baseline` reports its own `latency_ms` |
| `config.py` | `FAST_PATH` (on), `FAST_PATH_MAX_RISK` 0.15, `FAST_PATH_AMOUNT_MULTIPLE` 3 |
| `scripts/compare_paths.py` (new) | runs rules-only / AI-all / AI-fast-path on all 39 cases and prints quality, latency, cost; `sweep` mode explores the risk limit |
| `tests/test_fast_path.py`, `tests/conftest.py` | 17 tests → 271 in total (the fast path is off by default in tests so the LLM tests keep testing the LLM) |

## Measurements (39 evaluation cases, live)

| Config | Pass rate | Unsafe errors | Latency p50 / p95 | LLM-reviewed cases | Cost / decision | Total |
|---|---:|---:|---|---:|---:|---:|
| **A** rules only | 82.1 % | 6 | 0.1 ms / 0.1 ms | 0 | $0 | $0 |
| **B** AI on every case | **100 %** | **0** | 1,652 / 3,414 ms | 35 | $0.000517 | $0.0202 |
| **C** AI + fast path | **100 %** | **0** | 1,595 / 3,472 ms | 29 | $0.000433 | $0.0169 |

Decisions of B and C are **identical on all 39 cases**; 300 further synthetic transactions were compared too (test) – the fast path never changed an action.

Where the time goes: tool nodes take < 1 ms each; **the LLM call is ≈ 1.5–3 s of every AI decision** (p95 3.4 s is a slow LLM call, not the rules). Where the money goes: ≈ $0.0005 per LLM review, i.e. ≈ $0.58 per 1,000 decisions if every one is reviewed.

**Why the eval-set latency barely moves under C:** the evaluation set is deliberately full of risky/edge cases; only 6 of 39 are routine. On realistic traffic the picture differs:

| Fast-path risk limit | Share of the 1,000 synthetic transactions that skip the LLM | Fraud among skipped routed payments |
|---:|---:|---:|
| 0.10 | 17.7 % | 0 |
| **0.15 (default)** | **32.0 %** | **0** |
| 0.20 | 49.4 % | 1 |
| 0.25 | 54.4 % | 1 |
| 0.30 | 57.0 % | 1 |

At 0.15: ≈ 32 % fewer LLM calls → **LLM cost per 1,000 decisions $0.58 → ≈ $0.39** and 32 % of requests answered in milliseconds instead of ≈ 2 s. Going to 0.20 buys 17 more points of savings but lets one of the 12 (synthetic) fraud cases skip the reviewer – and the reviewer has never caught anything, so the decision is a risk-appetite call, exposed as config.

## Analysis – when is the LLM worth using?

- **Decision quality:** the LLM changed *no* decision in any evaluation (0 escalations on 39 cases; on Day 37 it agreed with the rules every time). Its measurable contribution is the **explanation** – and the deterministic template scores 10.0 on the rubric vs 9.5 for LLM text. So the honest value of the LLM here is readability and the concern list for human reviewers, not safer or better decisions.
- **Therefore** the LLM is kept where a person or an auditor will *read* the text or where a second opinion could matter: manual reviews, new customers, moderate/high risk, unusual amounts – and skipped for the unambiguous cases.
- **Fast-path candidates** (rules only, decidable without the LLM): clear declines (the LLM can never soften a decline), routine low-risk routes.
- **Trade-off table:** rules only = free/instant but no safety routes beyond the baseline (82 % on the eval set); AI-all = full coverage at ≈ $0.0005 and ≈ 1.7 s; AI + fast path = same decisions at ≈ 0.68× the cost on realistic traffic.

## How it was implemented (steps)

1. Latency timers on the baseline path (`latency_ms` in the API) and the AI path (per-node `timings_ms`, `graph_done.latency_ms`).
2. Token tracking + estimated cost (`usage.py`, from Day 32) captured per decision and summed per evaluation.
3. Comparison runner over identical cases for the three configurations.
4. Fast-path design: only outcomes where *the LLM cannot change the result* (decline) or where every risk indicator is quiet (routine); the LLM is never skipped for new customers, chargeback history, unusual amounts or anything a human will read.
5. Backstop checks (`new_customer`, `unusual_amount`, `chargeback_history`) are independent of the risk limit, so relaxing the limit cannot silently admit those cases (tested).

## Run & test

```bash
cd Day39
python -m scripts.compare_paths            # live: 3 configs x 39 cases (~$0.04)
python -m scripts.compare_paths sweep      # rules only: fast-path share by risk limit
python -m pytest                           # 271 offline tests
```
