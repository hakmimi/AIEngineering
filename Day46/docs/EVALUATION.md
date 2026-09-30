# Evaluation history and coverage (Weeks 1–2 of the decision agent)

## Results by version (AI agent = graph + LLM; baseline = rules only)

| Run | Agent version | Cases | Baseline pass | **AI pass** | AI unsafe errors | What the run showed |
|---|---|---:|---:|---:|---:|---|
| Day 36 (5 + 23 dry runs) | v1 | 23 | 73.9 % | – | – | dataset validation: only the safety-route cases fail for the rules-only agent |
| Day 37 `v1` | v1 | 31 | 64.5 % | 87.1 % | 4 | probes exposed card testing, amount anomaly, chargeback history |
| Day 38 `v2` | v2 | 39 | 82.1 % | **100 %** | 0 | fixes + hold-out variants (8/8) and guards not over-blocked |
| Day 41 `v3` | v3 | 45 | 75.6 % | **100 %** | 0 | policy constraints; no regression on the 39 earlier cases |

Other measurements: explanation rubric average 9.5–9.6 / 10 (LLM) vs 10.0 (template); latency p50 ≈ 1.7 s AI vs 0.1 ms rules; LLM cost ≈ $0.0005 per reviewed decision; fast path removes ≈ 32 % of LLM calls on realistic traffic with identical decisions.

## How the dataset is built

45 cases in seven categories: normal 11 · risky 6 · edge 4 · uncertain 2 · probe 8 · holdout 8 · policy 6. Expected outcomes are written as **business reasoning first** (`acceptable_actions`, `acceptable_providers`, expected route, required reason codes) and errors are classified by **direction**: `unsafe_error` (too permissive), `over_cautious`, `wrong_action`. The measuring stick itself is tested (33 tests): unique ids, valid transactions, expected providers really exist and could carry the payment, safety-route cases expect a human.

## Coverage notes – what is *not* covered (`python -m scripts.eval_coverage`)

| Dimension | Covered | Missing |
|---|---:|---|
| customer types / payment methods / merchant categories / currencies / policies | complete | – |
| countries | 8 / 15 | AE, CA, ES, FR, IT, MX, NL |
| providers selected | 5 / 6 | `zeta_budget` is never the best choice in any case |
| reason codes exercised by rules alone | 15 / 20 | `NO_ELIGIBLE_PROVIDER` (unreachable with the current provider table), `AI_ESCALATION`, `TOOL_ERROR`, `LOW_CONFIDENCE` (LLM/failure paths – covered by unit tests, and LOW_CONFIDENCE by two live cases), `INVALID_INPUT` (rejected at the API instead) |
| expected actions | route 20 · review 24 · decline 13 | real traffic is ~94 % routine payments; this set is deliberately edge-heavy |

## Honest limits

- Cases are written by one person; "expected" is business judgement, not ground truth from real disputes.
- 100 % on a set the agent was iterated against says the known weaknesses are fixed, not that unknown ones do not exist – the two hold-out sets (Day 38, Day 41) are the safeguard, and each was written after the corresponding fix.
- The synthetic fraud (12 cases in 1,000) is generated from a smooth risk model; the rules catch 25 % of it – the evaluation cases, not the synthetic population, are where the pattern rules earn their keep.
- No prompt A/B comparison was run for the decision agent (explanations already pass the rubric); that would need a judge and a larger set.
