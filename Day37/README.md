# Day 37 – First Full Evaluation: Baseline vs AI Agent

## Goal

Run the first complete, repeatable evaluation, **compare the rules-only baseline with the AI-enhanced graph agent**, find where each fails, group the failures, and derive the improvements Day 38 will implement.

```text
Eval Cases → Baseline Agent → AI Agent → Compare → Failure Analysis → Top 3 improvements
```

## What changed (vs Day 36)

| File | Change |
|---|---|
| `scripts/eval_full.py` (new) | runs **both** agents on every case; scores decisions *and* explanations; writes `full_<label>.json`, `full_<label>.csv` (one row per case) and `report_<label>.md`; groups failures by error type and category; lists the lowest-scoring explanations for manual reading |
| `data/eval/decision_cases.json` | +8 **probe** cases (31 total) aimed at plausible blind spots of the rules: card testing, anomalous amounts, chargeback history … added because the first 23 cases were passed 100 % by the AI agent |
| `evaluation.py` | an expected route may be `null` (probes test the *decision*, not the internal route) |
| `data/eval/full_v1.*`, `report_v1.md` (new) | the stored results of this run |
| `tests/test_eval_full.py` (new) | 7 tests → 221 in total |

## How it was done (steps 1–10)

1. **Baseline on all cases** and 2. **AI (graph + LLM) on all cases** – `scripts/eval_full.py v1`.
3. **Compare decisions** – action + provider per case; 6 of 31 decisions differ between the agents.
4. **Compare routes** – the rules-only agent has no `fallback`/`uncertain` routes.
5. **Score explanations** – deterministic rubric (Day 36) for both agents plus manual reading of the lowest three.
6. **Store results** – CSV/JSON/Markdown.
7. **Wrong decisions** and 8. **grouped failures** – below.
9. **Summary** and 10. **Top 3 improvements** – below.

Why the probe cases? The first 23 cases were written knowing the graph's safety routes, so a 100 % result for the AI agent was not evidence of much. A good evaluation must be able to fail: the probes encode fraud patterns the current rules never mention.

## Results (31 cases, live LLM)

| Metric | Baseline (rules) | AI (graph + LLM) |
|---|---:|---:|
| case pass rate | 64.5 % (20/31) | **87.1 % (27/31)** |
| action accuracy | 67.7 % | 87.1 % |
| route accuracy | 80.6 % | **100 %** |
| provider accuracy (when routed) | 100 % | 100 % |
| `unsafe_error` (too permissive) | 10 | **4** |
| `over_cautious` | 0 | 0 |
| explanation score (0–10) / pass | 10.0 / 100 % (template) | 9.52 / 100 % (LLM) |
| latency p50 | 0.1 ms | 1,752 ms |
| LLM cost for 31 cases | $0 | $0.0166 (≈ $0.0005 per LLM-reviewed case) |

Pass rate by category – baseline → AI: normal 100 → 100 %, risky 100 → 100 %, **edge 0 → 100 %**, **uncertain 0 → 100 %**, probe 38 → 50 %.

## Failure analysis

**Baseline** – 11 failures, all in categories the AI agent's safety routes cover: unknown country, inconsistent profile, extreme amount, borderline new customers, and one probe (`p07`, a gaming purchase by a new wallet customer that the uncertainty route catches).

**AI agent – 4 failures, all `unsafe_error`, all probes:**

| Case | What happened | Why |
|---|---|---|
| `p01_card_testing_digital` (1 USD, day-old account) | routed | risk is tiny; no rule for tiny amounts |
| `p02_card_testing_gaming` (2 GBP, age 0) | routed | same blind spot |
| `p03_grocery_5000` (returning customer, ~80× the typical basket) | routed | amount adjustment is **capped at +0.15**, so an absurd amount barely moves the risk |
| `p04_four_chargebacks` (safe country) | routed | chargeback adjustment is **capped at +0.30**, risk stays ≈ 0.35 < review threshold 0.45 |

The LLM reviewer never flagged any of them (no escalation, no disagreement): **the second opinion added readable explanations but no additional safety on these cases.** Grouping: 2× "missing pattern rule", 1× "score cap hides an anomaly", 1× "history under-weighted".

**Explanations:** all pass the rubric (≥ 8/10). The lowest three are uncertainty notes (8/10): correct, but they use the word "moderate/relatively higher" loosely and are longer than the 3-sentence ideal – a wording issue, not a correctness one.

## Top 3 improvements (implemented and re-measured on Day 38)

1. **Card-testing rule** – a *new* account paying a tiny amount in digital goods/gaming → manual review (fixes p01, p02).
2. **Amount-anomaly rule** – an amount far above the category's typical size (e.g. > 30× typical) → manual review regardless of the capped risk term (fixes p03).
3. **Chargeback-history rule** – ≥ 3 prior chargebacks → manual review even when the score is below the threshold (fixes p04).

Also noted for later: the LLM reviewer's value is explanation, not challenge – Day 39 weighs its ≈ 1.7 s and cost against skipping it for easy cases.

## Caveats

31 cases, written by one person; expected outcomes are business judgement, not ground truth from real disputes. A pass rate of 87 % here says "the safety routes work and four specific patterns are missing", not "87 % of real traffic is decided correctly".

## Run & test

```bash
cd Day37
python -m scripts.eval_full v2            # both agents, all cases (live LLM, ~1 minute)
python -m pytest                          # 221 offline tests
```
