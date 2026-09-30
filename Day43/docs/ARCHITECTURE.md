# Payment Routing Decision Agent – architecture (end of Week 2)

## One line

A FastAPI service that decides, for each payment, **route / manual review / decline**: deterministic rules and audited tool calls decide, business policies constrain, an LLM explains and may only make the outcome safer, and every decision leaves an audit record.

## Decision flow (LangGraph, 16 nodes)

```text
POST /decision  (API key + rate limit + Pydantic validation, request id)
   │
   ▼ input ─► policy_gate ── violation ─► policy_block ────────────────────────────────┐   (decline / review, no tools, no LLM)
                 │ ok                                                                   │
                 ▼                                                                      │
             route_input ── fallback ─► fallback ──────────────────────────────────────┤   (unknown country, extreme amount, inconsistent profile)
                 │ normal                                                               │
                 ▼                                                                      │
             risk_tool ── failure ─► tool_error ────────────────────────────────────────┤
                 ▼                                                                      │
              rules  (pattern rules: card testing, amount anomaly, chargebacks; risk thresholds)
                 │ decided (decline/review)                     │ needs a provider       │
                 │                                   provider_tool ─► cost_tool ─► select │
                 ▼                                              ▼                        │
        ┌─ fast_explain  (rules unambiguous: skip LLM)   ◄── after_baseline ──► llm_explain
        │                                                                         │ uncertain? ─► uncertainty_review
        ▼                                                                         ▼
      finalize  (control rules: the LLM may only turn route → manual review)  ◄───┴──────────────────────────────┘
        ▼
  constraint_guard  (independent re-check: policy + provider eligibility; fails safe, logs at ERROR)
        ▼
  audit record  (SQLite, insert-only, SHA-256)  →  response {decision, decision_id, graph trace, tool trace, usage, latency}
```
Generated diagram: [`graph.md`](graph.md).

## Layers

| Layer | Modules | Idea |
|---|---|---|
| Contracts | `schemas.py` | closed enums for actions and reason codes; a decision must carry ≥ 1 reason code and a provider iff routed |
| Data | `simulation.py`, `data_loader.py` | seeded synthetic world; hidden truth columns never reach the agent |
| Rules | `risk.py`, `decision_engine.py`, `routing.py`, `fast_path.py`, `policy.py` (+ `data/policies.json`) | exact, explainable, unit-tested; policies live in a table |
| Tools | `tools.py`, `tool_pipeline.py` | validated inputs and outputs, trace of every call; same decisions as direct calls (tested on 300 transactions) |
| LLM | `llm.py`, `prompts.py`, `ai_decision.py`, `grounding.py` | structured output, numeric grounding, may only escalate; template fallback |
| Orchestration | `decision_graph.py` | nodes are thin adapters; edges read state only |
| Trust | `audit.py`, `observability.py`, `usage.py`, `version.py` | one audit record per decision; JSON logs carry request id and decision id; agent version everywhere |
| Evidence | `evaluation.py`, `scripts/eval_full.py`, `eval_compare.py`, `eval_coverage.py`, `data/eval/` | 45 labelled cases, versioned results, error-direction scoring |

## Safety principles (each has tests)

1. **The LLM may make a decision safer, never riskier** – proven for every combination of model answers and all baseline outcomes.
2. **Every added mechanism only adds oversight** – fallback, uncertainty, patterns, policies and the guard can move a case toward manual review/decline, never toward routing.
3. **Unknown ⇒ human.** Missing data, failed lookups, unknown countries and untrusted profiles end in manual review with a specific reason code.
4. **Nothing is decided in the dark.** No decision without reason codes; no explanation with a number that is not in the data; no outcome without an audit record (or an explicit `audit_recorded=false`).
5. **Policies first and last.** Checked before any work and again after the final decision.

## Decision log

| Decision | Reason | Evidence |
|---|---|---|
| Rules decide, LLM explains | exactness, auditability, cost | the LLM changed 0 of 45 evaluated decisions; template explanations score 10.0 vs 9.5 for LLM text |
| Explicit pattern rules instead of re-weighting the risk score | the score's terms are capped and blind to combinations; re-weighting shifts every decision | v1 → v2: AI unsafe errors 4 → 0, no regression, hold-out 8/8 |
| Fast path skips the LLM for unambiguous cases | cost and latency without changing decisions | 32 % of synthetic traffic, decisions identical on 39 cases + 300 transactions |
| Policy gate before tools, guard after | a sanction needs no analysis; the guard catches upstream bugs | 6 policy cases; injected-bug tests |
| Audit is best-effort (`audit_recorded`) | availability over completeness (switchable) | tested failure path |
| One `unassessed_result` helper | the "risk unknown → human" pattern had been copied into four nodes | Day 42 refactor, all tests unchanged |

## Is the graph too complex?

16 nodes, but a normal decision visits 5–9 of them and every node except the LLM ones takes < 1 ms. Four nodes (`policy_block`, `fallback`, `tool_error`, `constraint_guard`) exist for clarity of the trace, not for logic. If it grows further the natural simplification is to merge `policy_gate` + `route_input` (both are pre-checks) and to make the three "unassessed" nodes one parameterised node; they are kept separate because a trace reading `policy_block` is easier to explain to an auditor than `pre_check(kind=policy)`.
