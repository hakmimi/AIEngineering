# Day 38 – Improve Decision Quality From the Evaluation Results

## Goal

Fix the highest-impact failure modes found on Day 37, **prove** the fix with the same evaluation (before/after, versioned), and check that the fixes generalise instead of merely memorising the probe cases.

```text
Failure Report → Logic Fix → Re-evaluation (versioned) → Improvement Report
```

## What changed (vs Day 37)

| File | Change |
|---|---|
| `decision_engine.py` | three **pattern rules** evaluated right after the decline rule (specific reason codes win over the generic `MEDIUM_RISK`): **card testing** (new account + ≤ 5 USD in digital goods/gaming), **amount anomaly** (≥ 30× the category's typical amount), **chargeback history** (≥ 3) → manual review |
| `schemas.py`, `explanations.py` | reason codes `CARD_TESTING_PATTERN`, `AMOUNT_ANOMALY` (+ explanation text); `PRIOR_CHARGEBACKS` reused |
| `config.py` | `CARD_TEST_MAX_USD` 5, `AMOUNT_ANOMALY_MULTIPLE` 30, `CHARGEBACK_REVIEW_COUNT` 3 |
| `version.py` (new) | `AGENT_VERSION = "v2"` + changelog; carried in `decision_made` logs and in every stored evaluation (`full_*.json`, report) |
| `scripts/eval_compare.py` (new) | before/after table, fixed / regressed / still-failing cases, hold-out pass rate |
| `data/eval/decision_cases.json` | +8 **hold-out** cases (39 total): variants written *after* the fix – other currencies/wallet/amounts – plus **guards** that must NOT be flagged |
| `data/eval/full_v2.*`, `report_v2.md` | results of this run |
| `tests/test_rules_v2.py` (new) | 32 tests → 254 in total |

## How it was done (steps 1–10)

1. **Top failure category (Day 37):** four `unsafe_error`s, all "plausible fraud pattern routed automatically" (both agents).
2. **Routing condition / rules** – the additive risk score caps the amount term at +0.15 and the chargeback term at +0.30, so extreme amounts and heavy histories could never push a payment over the review line. Cleanest fix: explicit pattern rules with their own reason codes rather than re-weighting the score (which would shift every decision).
3. **Missing context field** – none needed: the typical-amount table already existed.
4. **LLM explanation prompt** – unchanged: v1 explanations already passed the rubric (avg 9.5/10); the failures were rule gaps, not wording (the evaluation told us where *not* to spend effort).
5. **Fallback condition** – unchanged.
6. **Eval version label** – `AGENT_VERSION` in code, logs and results.
7–8. **Re-run and compare** – below.
9. **Document** – this file. 10. **Debug** – two rounds: an eval-compare bug when case sets differ (fixed to compare only common cases), and the hold-out cases added *after* the fix to test generalisation.

## Results

| Measure (same 31 cases) | v1 | v2 |
|---|---:|---:|
| **AI agent** pass rate | 87.1 % | **100 %** |
| AI `unsafe_error`s | 4 | **0** |
| AI cases fixed / regressed | – | 4 fixed (p01–p04) / **0 regressed** |
| Rules-only baseline pass rate | 64.5 % | 77.4 % (its remaining failures are the routes only the graph has) |
| explanation score (0–10) | 9.52 | 9.56 |

**Hold-out (8 new cases, never used to design the rules):** the AI agent passes **8/8** – the variants (4 EUR gaming, 3 GBP digital by wallet, 3,000 GBP groceries, five chargebacks) are caught, and the four guards are **not** blocked (an established customer paying 1 USD, 400 USD of groceries, two old chargebacks, a new customer paying 20 USD for digital goods). Whole 39-case set: AI 100 %, baseline 82.1 %.

**Side effect on realistic traffic:** on the 1,000 synthetic transactions the manual-review share goes 5.6 % → 6.1 % (+5 transactions) – the rules are narrow; fraud captured is unchanged (3 of 12 – see caveats).

## Caveats – read before trusting 100 %

- The fixes were designed from the failures of *these* probes and the hold-out variants were written by the same person knowing the fix: it shows the rules are not hard-coded to the exact numbers, **not** that fraud patterns I did not think of are covered. The synthetic dataset's 12 fraud cases were barely affected (25 % caught), because that fraud is generated from a smooth risk model, not from these patterns.
- Thresholds (5 USD, 30×, 3 chargebacks) are judgement calls – exposed as config so they can be tuned with real data.
- 39 cases still cannot estimate real-world precision/recall.

## Run & test

```bash
cd Day38
python -m scripts.eval_full v3                 # both agents, live LLM
python -m scripts.eval_compare v1 v2           # before/after
python -m pytest                               # 254 offline tests
```
