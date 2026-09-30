# Day 36 – Evaluation Dataset for the Decision Agent

## Goal

Measure decision quality instead of guessing: a labelled evaluation set with **expected** decisions, expected routes and an explanation rubric, plus a repeatable runner – built *before* optimising anything (Month 1's lesson: build the yardstick first).

```text
Eval Dataset → Decision Agent → Actual Decision → Expected Decision → Score
```

## What changed (vs Day 35)

| File | Change |
|---|---|
| `data/eval/decision_cases.json` (new, 23 cases) | 11 **normal** (must be processed), 6 **risky** (human or decline), 4 **edge** (agent must not decide alone), 2 **uncertain** (borderline); each with acceptable actions, acceptable providers, expected route, required reason codes |
| `scripts/make_eval_cases.py` (new) | the case definitions, written as business reasoning with a description per case |
| `data/eval/explanation_rubric.json` (new) | 5 criteria × 0–2 (states action, correct reason, grounded, business language, concise), pass ≥ 8 |
| `evaluation.py` (new) | loader with validation, `score_case` (action / provider / route / reasons + **error direction**), `summarize`, deterministic `score_explanation` |
| `scripts/eval_decisions.py` (new) | runner: `run <label> --mode baseline\|graph --limit N`, prints per-case results, saves JSON |
| `tests/test_evaluation.py` (new) | 33 tests – the measuring stick is itself tested (214 in total) |

## How it was implemented

1. **Scenarios (23)** – normal, risky, invalid/edge and uncertain, as required; e.g. routine grocery payment, VIP travel booking, new customer + 2,400 USD electronics, day-old account with three chargebacks, unknown country, 75,000 USD, "VIP" with a 20-day-old account, borderline new customer.
2. **Expected outcomes come from business reasoning, not from the agent.** Each case says *why* a human would expect that outcome. Where several answers are commercially fine, the case lists all of them (`acceptable_actions`, `acceptable_providers`) instead of forcing one.
3. **Expected route** – `normal`, `fallback` or `uncertain` (the graph's safety routes from Day 35).
4. **Explanation rubric** – written down first (`explanation_rubric.json`), then implemented deterministically; Day 37 adds LLM-written explanations to score.
5. **Error direction matters** – a wrong action is classified as `unsafe_error` (more permissive than any acceptable answer: routed what a human/decline should get), `over_cautious` (stricter than any acceptable answer) or `wrong_action` (between acceptable answers). In payments an unsafe error and an over-cautious error do not cost the same.
6. **Quality checks on the dataset itself** (tests): unique ids; every transaction valid; every expected provider exists and *could* carry the payment; cases labelled `fallback` really are fallback inputs and no others are; safety-route cases always expect `manual_review`; normal cases always allow `route`.
7. **Runner skeleton** – loads cases, runs the chosen agent (`baseline` = rules only, `graph` = full workflow with LLM), scores, prints and stores results.

## First runs (debug + refine)

*First 5 cases, rules-only agent:* **5/5 pass** (correct provider each time: local Israeli provider for the ILS grocery payment, bank-transfer specialist for the German utility bill, `alpha_pay` for the VIP travel booking …).

*All 23 cases, rules-only agent* (to validate the dataset; the official baseline-vs-AI comparison is Day 37):

| Category | Pass rate | Note |
|---|---:|---|
| normal (11) | 100 % | providers all in the acceptable sets |
| risky (6) | 100 % | new+large → review, chargeback pile-ups → decline |
| edge (4) | 0 % | the rules-only agent has no fallback route: it *routes* unknown-country and inconsistent-profile payments (unsafe) |
| uncertain (2) | 0 % | it routes borderline new customers instead of escalating |
| **overall** | **73.9 %** (17/23) · 5 `unsafe_error`s | |

This is the expected shape and a useful validation: the cases that fail are exactly the ones the Day 35 safety routes were built for, and the dataset does **not** reward doing nothing. A dataset where the baseline scored 100 % would have been too easy.

## Run & test

```bash
cd Day36
python -m scripts.make_eval_cases                       # regenerate data/eval/decision_cases.json
python -m scripts.eval_decisions run first5 --limit 5
python -m scripts.eval_decisions run mine --mode graph  # live: uses the LLM
python -m pytest                                        # 214 offline tests
```
