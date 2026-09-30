# Portfolio story - payment routing decision agent

*Numbers are from this repository's own runs (see the evidence table at the end). All data is synthetic. Nothing here ran in production.*

## Title and one-liner
**Payment Routing Decision Agent** - a FastAPI service that decides whether to route, review or decline each payment, using deterministic rules and audited tools as the decision-maker and an LLM only for explanation and for making outcomes *safer*.

## 5-line summary
1. Input: a payment event; output: `route` (with a provider), `manual_review` or `decline`, with reason codes and an explanation.
2. A LangGraph workflow runs policy checks, input routing, risk and provider tools, rules, an LLM review and a final independent guard.
3. The LLM cannot make a decision riskier: its only power is turning `route` into `manual_review`; ungrounded numbers in its text are rejected.
4. Every decision is stored in an insert-only, hash-protected audit table with the agent version, cost and latency.
5. Quality is measured on 45 labelled cases with error *direction* (unsafe vs over-cautious): rules-only 75.6% / 10 unsafe errors, full agent 100% / 0.

## Architecture bullets
- LangGraph state machine (16 nodes; a normal decision visits 5-9): policy gate -> input routing -> risk/provider/cost tools -> rules -> LLM review -> control rules -> constraint guard -> audit.
- Closed enums and Pydantic contracts for inputs, decisions, reason codes and responses; response models are tested so no field is silently dropped.
- Policies live in a table, are checked first *and* re-checked last; unknown data always ends in manual review with a specific reason code.
- Sync and async execution paths plus a bounded job queue (idempotent, backpressure, restart recovery) on SQLite.
- Layered configuration (defaults < YAML < environment; secrets env-only) and three selectable modes for experiments (baseline / ai / graph).

## Evaluation bullets
- 45-case labelled set (normal, risky, edge, uncertain, probe, policy, hold-out) scored on action, route, provider, reason codes and explanation quality.
- Error direction: rules-only made 10 *unsafe* errors, full agent 0; the LLM added none of that safety (the `ai` mode without policy gate still has 9 unsafe errors).
- Versioned evaluation runs v1-v4 with like-for-like comparison (v1's 31 cases: 31/31 vs 24/31).
- 100-event HTTP simulation: 0 failures, p50 1.5 s / p95 2.5 s, $0.000385 per decision, injected scenarios 17/17 handled as expected.
- 495 automated tests, including invariants under a hostile LLM stub.

## Production-oriented features
Structured JSON logging with request ids - retry with backoff and typed errors - rate limiting and API key - fast path that skips the LLM for unambiguous cases (25-32% of traffic, identical decisions) - audit with integrity check - `/ready` and `/health` - Dockerfile/compose (unbuilt, see limits) - CI-style checks (ruff, tests, secret scan).

## CV bullets (pick three)
- Built a payment-routing decision agent (FastAPI, LangGraph, OpenAI structured outputs) in which deterministic rules decide and the LLM may only escalate; cut unsafe decisions from 10 to 0 on a 45-case labelled evaluation set.
- Designed an evaluation harness with error-direction scoring, versioned runs and a 100-event HTTP simulation (p95 2.5 s, ~$0.0004 per decision), and used it to find that safety came from policy/pattern layers, not from the LLM.
- Added production controls to the service: hash-protected audit trail, async execution with a bounded job queue, layered configuration, numeric grounding of LLM output, and 495 tests (98% coverage).

## LinkedIn / GitHub description bullets
- **What:** an AI decision service for payment routing - rules and tools decide, an LLM explains and can only make outcomes safer.
- **Proof:** evaluated against a rules-only baseline on labelled cases, with error direction, latency and cost reported (and its limits stated).
- **Engineering:** LangGraph workflow, typed contracts, audit trail, async + queue, config layering, tests and CI-style checks.

## 2-minute interview explanation
"I wanted to understand AI *systems*, not prompts. The task is deciding what to do with a payment. I started with a rules baseline and measured it, because you cannot claim an LLM helps without a baseline. Then I added an LLM and found something I did not expect: it changed none of the decisions. The failures were policy, unknown-country and combination-of-risk cases, so I fixed those with a policy gate, a fallback route and explicit pattern rules, and re-ran the evaluation until unsafe errors were zero. I kept a hold-out set so I could not just tune to the tests, though it is still my own data. The LLM now writes explanations and can only escalate a payment to a human, never approve one, and anything it says that is not grounded in the data is thrown away. Around that I built what makes it operable: audit trail, versioning, async and a job queue, configuration, and measurement of cost and latency. What I would do next is get real labelled data and run it in shadow mode."

## How it maps to AI Engineer requirements
| Typical requirement | Where it shows |
|---|---|
| LLM integration with structured output | `llm.py`, strict JSON schema, grounding check, retries with typed errors |
| Agents / orchestration | LangGraph workflow, conditional routing, tool layer with traces |
| Evaluation | `evaluation.py`, `scripts/eval_full.py`, `compare_modes.py`, versioned runs, error direction |
| Reliability and safety | invariants, guard, policy table, unknown => human |
| Cost and latency awareness | usage tracking, fast path, async benchmark, cost per decision |
| Deployment / operations | config layering, `/ready`, Docker files, metrics, dashboard, audit |
| Testing | 495 tests, hostile-LLM invariants, docs/contract tests |

## Honesty review - claims and what would falsify them
| Claim | Evidence | Falsified if |
|---|---|---|
| 10 -> 0 unsafe errors | `data/eval/full_v4.json` | a case is added that the guard misses (expected; the set is small and self-written) |
| LLM changed no decisions | Day 40 / final evaluation | a model or prompt change - re-run the evaluation |
| p95 2.5 s, $0.000385 | `data/simulation/week3_analysis.json` | different traffic mix or model pricing |
| 495 tests, 98% coverage | `pytest --cov` | n/a - re-run |

Never say: "production", "real customers", "improved fraud detection", "100% accurate" (without "on 45 self-written cases after tuning"), "the LLM makes the decisions".
Docker was not built on the development machine; the CI workflow has run only locally.

**Yours to complete:** the plan asks to connect the project to *your own background in decision systems*. Only you know that - add one sentence to the 2-minute explanation (what decision systems you have worked on and what is the same here).
