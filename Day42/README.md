# Day 42 – Week 2 Consolidation (Decision Agent)

## Goal

Consolidate Week 2 (Days 36–41: evaluation, improvement, cost/latency, audit, policy guardrails) into a mid-month technical summary: cleaner code, a reviewed graph, evaluation and coverage documentation, an updated architecture write-up, and the priorities for Week 3.

## What changed (vs Day 41)

| Area | Change |
|---|---|
| Refactor | the "risk unknown, so a human decides" construction was copied into four places (policy block, fallback, tool error, tool-pipeline failure); it is now one function, `decision_engine.unassessed_result()`, and `UNKNOWN_RISK_SCORE` has one home (`risk.py`). No behaviour change: all 331 tests pass unchanged (two assertions that referred to the moved constant were updated) |
| Review | `docs/ARCHITECTURE.md`: full 16-node flow, layers, five safety principles (each with tests), decision log with evidence, "is the graph too complex?" |
| Evaluation | `docs/EVALUATION.md`: results by version (v1 → v3), dataset design, honest limits; `scripts/eval_coverage.py` (new): which countries, providers, reason codes, policies the 45 cases cover and which they miss |
| Verification | `scripts/e2e_smoke.py` (new): 11 live scenarios through the real API incl. audit retrieval → **11/11 passed** |
| Diagram | `docs/graph.md` regenerated from the compiled graph (includes policy gate, fast path, constraint guard) |

## Week 2 in numbers

| | Day 37 → Day 41 |
|---|---|
| AI agent pass rate | 87.1 % (31 cases) → **100 %** (45 cases), unsafe errors 4 → **0** |
| Rules-only baseline | 64.5 % → 75.6 % (it lacks the graph's safety routes and policies: 10 unsafe errors on 45 cases) |
| New protections | 3 pattern rules · 4 policies enforced twice (gate + guard) · audit trail with integrity hash · fast path |
| Cost / latency | ≈ $0.0005 and ≈ 1.7 s per LLM-reviewed decision; ≈ 32 % of realistic traffic skips the LLM |
| Tests | 154 → **331**, all offline, ≈ 24 s |

## Reviews (steps 1–4)

- **Eval results** – see `EVALUATION.md`; the important lesson: the first evaluation the AI agent "passed" at 100 % was too easy, and only the added *probe* cases (fraud patterns nobody had encoded) produced failures worth fixing.
- **Cost/latency** – the LLM is ≈ 99.9 % of latency and 100 % of cost, yet changed 0 of 45 decisions; its value is readable explanations. Hence the fast path, and the recommendation to keep it only where a human or auditor reads the text.
- **Audit records** – one per decision, joined to runtime logs by `decision_id`; integrity check detects edits, not a determined attacker with write access (documented).
- **Guardrail behaviour** – the guard has never fired on real inputs (as designed); its tests inject upstream bugs to prove it would.

## Coverage gaps found by the new coverage script

7 of 15 countries never appear in a case; provider `zeta_budget` is never the winner in any case; four reason codes are exercised only by unit tests or LLM-dependent cases. These are **evaluation gaps, not known failures** – listed in the Week 3 backlog.

## Week 2 summary

Started Week 2 with a hybrid agent that looked correct because nothing tested it. Built an evaluation set with business-reasoned expectations and error *direction*; it showed the AI agent beating the rules-only baseline (87 % vs 65 %) but failing four fraud-pattern probes – all of which the LLM reviewer had also missed. Fixed them with explicit pattern rules (not by re-weighting a score), verified on a hold-out set and guard cases, then measured what the LLM costs, cut 32 % of its calls with a fast path that provably changes no decision, made every decision auditable, and put non-negotiable policies in front of and behind the whole flow.

## Week 3 backlog (plan: Days 43–48 simulation, async, queue, monitoring, modes, consolidation)

1. **Simulator (Day 43):** replay ≥ 100 events against the API, collect latency/route/cost distributions – this also tests the *rate* at which the safety routes fire on realistic traffic.
2. **Async / concurrency (Day 44):** the LLM call blocks a worker for ≈ 2 s; measure throughput sync vs async.
3. **Queue + status endpoint (Day 45)** for slow decisions.
4. **Monitoring (Day 46):** p95 latency, route distribution, cost per decision from the existing structured logs and audit table.
5. **Modes/config (Day 47):** baseline / AI / graph selectable and logged.
6. **Evaluation coverage:** add cases for the 7 missing countries, a case where `zeta_budget` should win, and a provider-outage scenario; velocity/cumulative-limit policies.
7. **Calibrate thresholds with real data:** risk review (0.45), fast-path limit (0.15), card-test amount (5 USD) are judgement calls exposed as config.

## Run & test

```bash
cd Day42
python -m pytest                        # 331 offline tests
python -m scripts.e2e_smoke             # live, needs OPENAI_API_KEY
python -m scripts.eval_coverage
python -m scripts.eval_full v5          # live: both agents on all cases
python -m scripts.draw_graph
```
