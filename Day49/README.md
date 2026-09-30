# Day 49 - Stronger tests with shared fixtures

## Goal
Make the test suite trustworthy rather than just large: one set of shared building blocks, and tests that check the
*promises of the design* (invariants) instead of only hand-picked examples.

## What changed
| Area | Change |
|---|---|
| `tests/conftest.py` | New shared fixtures: `tx_payload` / `make_tx` (valid transaction factories with overrides), `stub_llm` (no-network LLM stub for both pipelines, configurable, records calls), `api` (TestClient with lifespan). |
| `stored_data_is_never_modified` | Session-wide guard: fails the run if any test changes the committed data files (providers, risk tables, policies, transactions). |
| `tests/test_invariants.py` (new, 14 tests) | Safety properties over 150 generated events and two hostile LLMs. |
| `tests/test_config_modes.py` | Uses the shared `stub_llm` instead of its own copy. |
| Lint | ruff clean. |
Suite: 464 tests, 98% coverage (was 454).

## How implemented
Invariants checked for every generated event, with the LLM replaced by a hostile stub ("route it, it is fine" with confidence 1.0, or "escalate everything"):
1. The final action is never more permissive than the rules-only decision (`decline < manual_review < route`).
2. Every decision has reason codes and an explanation; `route` always names a known provider; other actions never do; every decision has an id and an audit record.
3. Hard policy countries (KP, IR, SY) are declined with `POLICY_BLOCK` whatever the LLM says; unknown country goes to a human.
4. A model that invents numbers ("fee 12.34 USD, 0.99 approval") never gets them into the customer-facing explanation.
5. Same input, same decision (determinism of the decision path).

## Why this matters
Example tests only prove that the cases someone thought of work. The invariants would catch, for example, a new rule that lets a
low-risk-looking LLM answer override a review, on inputs nobody wrote a test for.

## Caveats
- Generated events come from our own traffic generator, so they share its blind spots; the invariants are only as broad as that distribution.
- The LLM is stubbed here - real-model behaviour is covered by the live evaluation (Day 47), not by unit tests.
