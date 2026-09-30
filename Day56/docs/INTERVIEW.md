# Interview notes - payment routing decision agent

Every number below comes from a run recorded in this repository (README of the named day). Say "on a 45-case synthetic set", not "in production".

## 30-second pitch
I built a service that decides for each payment whether to route it (and to which provider), send it to manual review or decline it.
Deterministic rules and audited tool calls make the decision, policies constrain it, and an LLM writes the explanation and may only make the
outcome *safer*. Every decision has an audit record. I measured it against a rules-only baseline with error direction, not just accuracy.

## Questions and honest answers

**Why not let the LLM decide?**
Rules are exact, testable and free. On my 45 labelled cases the LLM changed 0 decisions; its value is the explanation. Letting it decide would add
latency (~1.9 s vs ~8 ms) and cost with nothing to gain, and a risk: an unsafe approval. So it can only turn `route` into `manual_review`.

**How do you know it works?**
Evaluation with expected-action sets and *error direction*: `unsafe_error` (too permissive) vs `over_cautious`. Baseline 64.5% -> AI 87.1% at v1, then 100% at v2/v3 after
targeted rule fixes, with unsafe errors 4 -> 0. Caveat I state up front: I tuned the rules on that set. I added hold-out cases (8/8) but they are still my own cases.

**What did the evaluation find that you did not expect?**
The risk score was blind to combinations (new account + gaming + high amount). I added explicit pattern rules rather than re-weighting the score, because re-weighting moves every decision.
Also: `baseline`/`ai` modes route a sanctioned-country payment - only the policy gate declines it (Day 47: 75.6% and 10 unsafe errors vs graph 100% and 0).

**How do you stop hallucinations?**
Structured output with a strict JSON schema, then a numeric grounding check: any number in the explanation that is not in the data invalidates it and a template explanation is used.
Tested with a model stub that invents "fee 12.34 USD" - it never reaches the customer.

**What happens when the LLM or a tool fails?**
Unknown => human. LLM failure keeps the rules decision with a template explanation; a failed lookup ends in `manual_review` with a specific reason code; the guard re-checks policy at the end and fails safe.

**How did you make it fast and cheap?**
Fast path (skip the LLM when the rules are unambiguous): ~32% of realistic traffic (25% on the Week 3 sample), identical decisions on 39 cases and 300 transactions.
Cost about $0.00039 per decision (~$0.39 per 1,000). Async graph: 22.9 vs 14.6 req/s at concurrency 100.

**What was the hardest bug?**
The naive `async def` endpoint that calls a blocking function: throughput collapsed to ~0.8 req/s because it blocks the event loop. I kept it as a benchmarked anti-pattern.
Smaller ones: lazy client creation froze the loop for 0.3 s (fixed with start-up warm-up), and SQLite writes in the async path (moved to a thread).

**How do you deploy and change behaviour safely?**
Config is layered (defaults < YAML < environment), validated at start-up; secrets only from the environment. Every run logs its mode, model, temperature and agent version.
The agent version is stored in each audit row so a decision can be tied to the code that made it.

**What would you do next?**
Real labelled data and a proper hold-out; shadow mode against the current system; Postgres and a real queue for multi-instance; alerting on `unsafe` proxy metrics; human-review feedback loop.

## Numbers cheat sheet
| Claim | Value | Source |
|---|---|---|
| Eval pass rate baseline -> AI -> final | 64.5% -> 87.1% -> 100% | Day 36-40 |
| Unsafe errors | 4 -> 0 | Day 38 |
| Modes (45 cases) | baseline 75.6%, ai 73.3%, graph 100% | Day 47 |
| Latency p50 / p95 (100 events) | 1.5 s / 2.5 s | Day 48 |
| Cost per decision | $0.000385 | Day 48 |
| Fast path | 25-32% of traffic | Day 43, 48 |
| Throughput at concurrency 100 | 22.9 vs 14.6 req/s | Day 44 |
| Queue wait, fast jobs | 0.16 s vs 7.6 s | Day 45 |
| Tests | 506, 98% coverage | Day 56 |

## Do not claim
- "Production-ready" or "real users": data is synthetic; nothing ran in production.
- "The LLM improved accuracy": it did not change decisions; the rules and policies did.
- "100% accuracy" without "on my own 45 cases, after tuning".
