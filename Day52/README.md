# Day 52 - Response schema polish and examples

## Goal
Make the API's output a real contract: typed, documented, validated on every response, with real examples that cannot drift.

## What changed
| File | Change |
|---|---|
| `responses.py` (new) | `DecisionResponse` (for `/decision`, `/decision/async`), `ModeDecisionResponse` (for `/decide`; mode-specific extras pass through), `ErrorResponse`, and the documented error table (401/422/429/503). Field descriptions say what each field means and which one a caller must act on. |
| `main.py` | `response_model=` and `responses=` on the three decision endpoints; OpenAPI now shows success and error shapes. |
| `schemas.py` | Example request on `Transaction`. |
| `scripts/make_examples.py` | Runs four scenarios against the API with the live model and stores `docs/examples/*.json` + `docs/EXAMPLES.md` (routine route, policy decline, unknown country, amount anomaly). |
| `tests/test_responses.py` (new, 10 tests) | Contract per endpoint; no produced key dropped by the model on 5 different routes; async == sync shape; examples validate; errors share a shape; OpenAPI lists error responses. |
| `tests/test_async.py` | Its fake results now return contract-valid payloads (the contract correctly rejected `{"ok": True}`). |
| `docs/API.md`, `docs/README.md` | Regenerated / indexed. |
Suite: 479 tests, ruff clean.

## How implemented
FastAPI's `response_model` validates and *filters* the response - a key that is not declared is silently removed. That is the dangerous part,
so a test runs the graph over five different situations (normal, policy, unknown country, extreme amount, new account) and asserts that every key the
service produces is declared in the model. Adding a field to the graph without declaring it fails the test instead of vanishing from the API.

## Caveats
- `/decide` uses `extra="allow"` because the baseline mode returns a different payload (`risk`, `candidates`); only the shared core is guaranteed there.
- Examples show real model output at the time they were generated; explanation text will differ on a re-run, decisions should not.
- Error bodies from FastAPI's own auth/rate-limit path carry `detail` only; `request_id` is guaranteed only for application errors (and always in the `X-Request-ID` header).
