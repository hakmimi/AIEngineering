# Day 29 – Decision-Agent Project: Problem, Architecture, Data Model

*Month 2 starts here: a new project – a **payment-routing decision agent** – built on the engineering habits from Month 1 (typed contracts, request-id logging, one retry layer, evaluation before optimisation).*

## Goal

Define the business problem, the decision flow and the domain data model **before writing any decision logic**: what the agent must decide, what information it needs, what the LLM may and may not do, and which API it exposes.

```text
Business Event → API → Decision Agent → Rules / Tools / LLM → Decision Output
```

## What changed (this day creates the project)

| Deliverable | Where |
|---|---|
| Problem statement, use case, decision outputs, deterministic-vs-LLM table, agent flow, planned endpoints, success criteria | [`docs/DESIGN.md`](docs/DESIGN.md) |
| Domain model: `Transaction` (input), `Decision` (output), closed enums for currency, method, category, customer type, `Action`, `ReasonCode` | `schemas.py` |
| 5 diverse sample events (routine grocery, new-customer big electronics, risky wallet payment, unsupported bank-transfer combo, VIP travel) | `data/sample_events.json` |
| Runnable skeleton: `GET /health`, `POST /events/validate` | `main.py` |
| Reused infrastructure from Month 1: config pattern, typed errors, request-id JSON logging, retry layer, OpenAI client, API-key/rate-limit | `config.py`, `errors.py`, `observability.py`, `resilience.py`, `openai_client.py`, `security.py` |
| 35 tests (schema validation, decision contract, sample events, API) | `tests/test_schemas.py` |

## How it was done (steps 1–10)

1. **Problem** – decide *whether* and *where* to process each transaction, trading approval probability, cost and risk, with explanations a regulator can audit.
2. **Use case** – payment routing + risk decision (alternatives: workflow automation, claims triage) – measurable outcomes, auditable rules, an obvious safe failure mode (human review).
3. **What information does the agent need?** Amount + currency, customer country, merchant category, customer type and account age, payment method, chargeback history → the `Transaction` model. Every field is typed; unknown fields are rejected (`extra="forbid"`); amount limits, ISO country format, timezone-aware timestamps, no future dates, and a cross-field rule (a "new" customer cannot have a 200-day-old account).
4. **Possible outputs** – exactly three actions (`route`, `manual_review`, `decline`); a decision must have ≥ 1 reason code from a closed enum, a bounded risk score, and a provider **iff** the action is `route`.
5. **What should the LLM do and not do?** Deterministic code owns validation, risk, eligibility, cost/approval math, ranking and policy. The LLM only **explains** in business language and gives an **advisory second opinion**. Guiding rule: *the LLM may make a decision safer, never riskier.*
6. **Agent flow** – validate → risk lookup → eligible providers → score/select → (LLM explain + challenge) → policy constraints → audit → decision; LLM failure degrades to a deterministic explanation or manual review.
7. **API plan** – health, validate, baseline, AI, graph decision, audit, jobs/status (table in `DESIGN.md` with target days).
8. **README concept** – this file and `DESIGN.md`.
9. **Sample events** – five events chosen to trigger different paths (low risk, high amount + new customer, high risk, no eligible provider, VIP).
10. **Review** – contracts are tested; the design lists success criteria (match rate vs expected outcomes, safety, latency/cost, 100 % explainability).

## Run & test

```bash
cd Day29
pip install -r requirements-dev.txt
python -m pytest                         # 35 tests, offline
uvicorn main:app --reload                # POST /events/validate with data/sample_events.json items
```
