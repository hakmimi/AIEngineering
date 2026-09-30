# Payment Routing Decision Agent

A FastAPI service that decides for each payment whether to **route** it (to which provider), send it to **manual review**, or **decline** it.
Deterministic rules and audited tools make the decision, business policies constrain it, and an LLM writes the explanation and may only make the
outcome *safer*. Every decision leaves a hash-protected audit record.

> Learning project (Month 2 of an AI-engineering plan). All data is synthetic; nothing has run in production. Limits are listed below and in `docs/`.

## Quick start
```bash
cp .env.example .env                  # add OPENAI_API_KEY (the service also runs without it: rules-only)
pip install -r requirements-dev.txt
uvicorn main:app --reload             # http://localhost:8000/docs   |   /ready
python -m scripts.demo                # 9-step guided tour (add --offline for no key)
python -m pytest                      # 506 tests, offline, ~1 min
docker compose up --build             # NOT verified - see Limits
```

## What it does
```
POST /decision  ->  policy gate -> input routing -> risk / provider / cost tools -> rules -> LLM review
                    -> control rules -> constraint guard -> audit record -> {decision, reason codes, explanation, trace, cost}
```
- **The LLM cannot make a decision riskier** - its only power is turning `route` into `manual_review`; numbers it invents are rejected.
- **Unknown means a human**: unknown country, failed lookup or untrusted profile ends in manual review with a specific reason code.
- **Policies first and last**: sanctions are declined before any tool or model runs and re-checked at the end.

## Results (synthetic data, live model, temperature 0)
| | Rules only | Full agent |
|---|---:|---:|
| Pass rate (45 labelled cases) | 75.6% | 100% |
| Unsafe errors | 10 | 0 |
| p50 latency | 0.1 ms | 1.9 s |

100-event HTTP simulation: 0 failures, p95 2.5 s, $0.000385 per decision, fast path skipped the LLM for 25% of events.
The LLM changed none of the evaluated decisions: the safety comes from the policy gate, fallback route and pattern rules; the LLM provides explanations.
Details and caveats: `docs/FINAL_EVALUATION.md`.

## Where to look
| | |
|---|---|
| `docs/` | index in `docs/README.md`: system diagrams, API reference, examples, evaluation, interview notes, portfolio story, limitations and roadmap, checklist |
| `decision_graph.py`, `decision_engine.py`, `policy.py` | the workflow, the rules, the policy table |
| `llm.py`, `grounding.py`, `ai_decision.py` | structured output, grounding check, LLM review |
| `audit.py`, `jobs.py`, `metrics.py`, `config.py`, `modes.py` | audit trail, job queue, metrics, layered config, mode selector |
| `scripts/` | evaluation, simulation, benchmarks, demo, fresh-checkout test |

## Limits (read before relying on any number)
- 45 self-written evaluation cases, tuned against; 100% is a regression guard, not a forecast.
- Docker image never built; the CI workflow has not run on GitHub (its steps pass locally).
- Single process with SQLite and an in-memory queue.

---

# Day 56 - Final demo, review and next roadmap

## Goal
Finalize the project: a demo that works end to end, a last full verification, an honest list of weaknesses, and a plan for the next four weeks - without adding features.

## What changed
| File | Change |
|---|---|
| `scripts/demo.py` | 9-step guided tour through the real API (ready, fast path, model-reviewed decision, policy decline, unknown -> human, anomaly, audit integrity, error handling, config, metrics). Exit code 0 only if every step behaves as claimed. `--offline` uses a stub model. |
| `tests/test_demo.py` | Runs the offline demo as a test (with no API key). |
| `scripts/check_secrets.py`, `tests/test_repo_hygiene.py` | Secret scanner brought over from Project A; tests for the scanner, for a clean project, and for a valid CI workflow. |
| `../.github/workflows/ci.yml` | Now targets `Day56` (ruff, secret scan, pytest with 95% coverage gate, no API key). Previously it pointed at Day27 - the wrong project. |
| `docs/LIMITATIONS_AND_ROADMAP.md` | Where the model fails, weak data, weak system, data backlog, four-week roadmap. |
| `docs/CHECKLIST.md` | What is verified by a command, what only partly, what not at all. |
| `README.md` | Rewritten as the project README. |

## Verification run on Day 56
| Check | Result |
|---|---|
| `pytest --cov=. --cov-fail-under=95` | 506 passed, 98% coverage |
| `ruff check .` | clean |
| `python -m scripts.check_secrets` | no secrets found |
| `python -m scripts.demo` (live model) | PASSED (9 steps + 2b) |
| `python -m scripts.e2e_smoke` (live model) | 11/11 scenarios |
| `python -m scripts.fresh_run` (new venv, no key) | 503 passed, 3 skipped; server ready; policy decline; audit integrity True |
| `python -m scripts.eval_full v4` (Day 54) | 100%, 0 unsafe errors, no regression vs v3 |

## What the last review found
- The CI workflow still pointed at Project A (Day27); the portfolio claimed a "secret scan" that Project B did not have. Both are now real (and tested), not just described.
- The routine demo payment took the fast path (no model call), so the tour would never have shown the LLM - added step 2b with a payment that reaches it.

## Not verified
Docker image build/run; the workflow on GitHub itself; real traffic. See `docs/CHECKLIST.md`.

## How to use the four-week plan
Week 1 of `docs/LIMITATIONS_AND_ROADMAP.md` is only about turning the two unverified items into verified ones, before any new feature.
