# Payment Routing Decision Agent - design

## Problem statement

An online payment platform receives a stream of transactions. For each one it must, within a couple of seconds, decide
**(a) whether to process it at all** and **(b) which payment provider (PSP) should carry it**, balancing three things
that pull in different directions: approval probability, cost (fees), and risk (fraud / chargebacks). Decisions must be
**explainable and auditable** - a regulator or a support agent must be able to see *why* a payment was routed, reviewed or
declined.

The project turns a data-science background (risk scoring, cost/approval trade-offs) into an AI-engineering system:
a **hybrid** where deterministic logic makes the decision and an LLM explains and cautiously challenges it.

Example use case chosen: **payment routing + risk decision** (alternatives considered: workflow automation, claims triage).
It was chosen because outcomes are measurable, the rules are auditable and the safe failure mode (send to a human) is obvious.

## Business event (input)

`Transaction` (see `schemas.py`): id, timestamp (timezone-aware), amount, currency, customer country, merchant category,
customer type (new/returning/vip), payment method (card/bank_transfer/wallet), customer account age in days, prior chargebacks.
Invalid input is rejected at the API (422) before any decision logic runs.

## Decision outputs

| Action | Meaning | Extra fields |
|---|---|---|
| `route` | approve and send to a provider | `selected_provider`, `expected_cost`, `expected_approval_probability` |
| `manual_review` | a human decides (also the safe fallback for uncertainty) | reason codes |
| `decline` | do not process | reason codes |

Every decision carries `risk_score` (0-1), a non-empty list of `reason_codes` (closed enum: `HIGH_RISK`,
`NEW_CUSTOMER_HIGH_AMOUNT`, `NO_ELIGIBLE_PROVIDER`, `CHEAPEST_ELIGIBLE`, `POLICY_BLOCK`, ...) and optional prose `explanation`.

## What is deterministic and what uses the LLM

| Step | Owner | Why |
|---|---|---|
| Input validation | code (Pydantic) | exact, cheap, never delegated |
| Risk score | code (rule table) | auditable, reproducible, unit-testable |
| Provider eligibility (country/currency/method/limits/risk tolerance) | code | hard constraints must never be "probably right" |
| Cost and approval-probability estimate | code (tools) | arithmetic belongs outside the LLM |
| Provider ranking + action (baseline) | code | the decision of record; also the benchmark for the AI |
| Policy constraints (sanctions, limits) | code | non-negotiable, applied last and can only make a decision more conservative |
| **Explanation in business language** | **LLM** | turns reason codes + numbers into readable text |
| **Second opinion ("challenge")** | **LLM, advisory** | may recommend escalation to manual review, **never** the reverse |

Principle: *the LLM may make a decision safer, never riskier.*

## Agent flow

```text
Transaction ─► validate ─► risk lookup ─► eligible providers ─► score & select (baseline)
            ─► [LLM: explain + challenge] ─► policy constraints ─► audit record ─► Decision
                     │ LLM unavailable / uncertain ─► deterministic explanation or manual_review
```

## Planned API

| Endpoint | Purpose | Day |
|---|---|---|
| `GET /health` | liveness | 29 |
| `POST /events/validate` | validate + normalise a transaction | 29 |
| `POST /decision/baseline` | deterministic decision | 31 |
| `POST /decision/ai` | baseline + LLM explanation/challenge | 32 |
| `POST /decision` (graph) | LangGraph workflow with routing and fallback | 34-35 |
| `GET /decision/audit/{id}` | full audit record | 40 |
| `POST /jobs`, `GET /status/{id}` | queued processing | 45 |

## Success criteria

Decision quality (match rate vs expected outcomes on an evaluation set), safety (no decision more permissive than the
baseline/policy allows), latency and cost per decision, and 100 % explainability (every response has reason codes).
