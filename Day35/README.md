# Day 35 – Routing and Fallback in the Decision Graph

## Goal

Make the agent safer and more production-like: send inputs it should not decide alone straight to a human (**fallback route**), and send *routed* decisions it is not sure about to a human too (**uncertainty review**) – with logged reasons, an explanation for the human, and tests for normal, invalid and uncertain cases.

```text
Transaction → route_input ─ normal ──► tools → rules → LLM review ─ confident ─► finalize → Decision
                         └ fallback ─► manual review (no tools, no LLM)            └ uncertain ─► uncertainty_review ─► manual review
```

## What changed (vs Day 34)

| File | Change |
|---|---|
| `routing.py` (new) | pure functions: `classify_input(tx)` (fallback route) and `uncertainty_signals(...)`; thresholds as named constants |
| `decision_graph.py` | new nodes `route_input`, `fallback`, `uncertainty_review`; conditional edges after `route_input` and `llm_explain`; uncertainty computed inside `llm_explain` (where the review is at hand) and stored in state; `finalize` escalates with reason `LOW_CONFIDENCE` |
| `prompts.py` | `UNCERTAINTY_PROMPT` + schema: 2 sentences telling the human *what is uncertain and what to check* (no invented numbers, never "fraud"/"safe") |
| `ai_decision.py` | `apply_control_rules(..., escalation_code)`; the API response reports `graph.route` and `graph.route_reason` |
| `schemas.py`, `explanations.py` | reason codes `UNKNOWN_COUNTRY`, `EXTREME_AMOUNT`, `INCONSISTENT_PROFILE`, `LOW_CONFIDENCE` |
| `tests/test_routing.py` (new), `tests/test_graph.py` | 27 new tests → 181 in total |

## Routes and rules

| Route | When | What happens | LLM / tools |
|---|---|---|---|
| **fallback** | country not in the risk tables · amount > 50,000 USD · `returning` customer with account < 7 days · `vip` with account < 180 days | manual review with a specific reason code + template explanation | none |
| **normal** | everything else | tools → rules → LLM review → controlled decision | as before |
| **uncertain** | a *routed* decision where the LLM disagrees, its confidence < 0.5, or a **new customer sits within 0.05 below the review threshold** | manual review, reason `LOW_CONFIDENCE`, LLM-written note for the human (template if the LLM fails or is ungrounded) | +1 LLM call, only on this route |

Invariants (tested): only routed decisions can become uncertain (review/decline are already safe); LLM *unavailable* is **not** an uncertainty signal; ungrounded numbers in the uncertainty note are replaced by the template; for every combination of input and LLM answer the final action is never more permissive than the baseline's – the new routes can only **add** human oversight.

## How it was implemented

1. **Routing cases** – three routes, above.
2. **Edge-case / invalid inputs** – schema-invalid input is already a 422; these are *schema-valid but untrustworthy* inputs: data-quality problems (inconsistent profile), missing reference data (unknown country) and out-of-policy size (extreme amount). Treating them as review cases beats guessing a risk score.
3. **Router node vs conditional edges** – nodes decide and write to state; edges only read it (an early attempt to compute uncertainty inside the edge function silently lost the value because LangGraph passes edges a copy of the state – it now lives in `llm_explain`'s update).
4. **Uncertainty explanation prompt** – separate from the review prompt: it explains the *doubt* for a human reviewer.
5. **Logging** – `graph_route route=… reason=…`, `graph_uncertain signals=[…]`; per-node timings as before.

## Live examples

| Input | Route | Result |
|---|---|---|
| country `ZZ` | fallback | manual review, `UNKNOWN_COUNTRY` – "…country is not covered by the risk tables" |
| new BR gaming customer, risk 0.444 (just under 0.45) | uncertain (`borderline_risk_new_customer`) | manual review, `LOW_CONFIDENCE` + LLM note about the borderline factors |
| `vip` account 20 days old | fallback | manual review, `INCONSISTENT_PROFILE` |

On the 300-transaction equivalence test: > 250 stay on the normal path with decisions identical to Day 34; fewer than 50 are affected by the new routes.

## Run & test

```bash
cd Day35
python -m pytest                     # 181 offline tests
python -m scripts.draw_graph         # regenerate docs/graph.md
```
