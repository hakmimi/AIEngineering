# Day 31 – Baseline Decision Engine (rules only)

## Goal

Build the deterministic decision engine **before** using any LLM: the decision of record, the benchmark the AI version must beat, and the answer to *"what can rules solve better than LLMs?"*.

```text
Transaction → Risk → Hard rules (decline / review) → Eligibility → Score providers → Select → Decision + reason codes
```

## What changed (vs Day 30)

| File | Change |
|---|---|
| `risk.py` (new) | `compute_risk(tx)` – transparent table-based score `0.45·country + 0.35·category + customer + amount + chargebacks`, with every component returned |
| `decision_engine.py` (new) | `decide_baseline(tx)`: risk rules → eligibility (`ineligible_reason`) → scoring (`score_provider`) → selection with reason codes; logs a `decision_made` event with inputs and outputs |
| `explanations.py` (new) | deterministic explanation template (fallback for the LLM later); test proves every reason code has text |
| `main.py` | `POST /decision/baseline` → decision + risk breakdown + ranked candidates + rejected providers with causes |
| `schemas.py`, `config.py` | new reason code `ONLY_ELIGIBLE_PROVIDER`; thresholds `RISK_DECLINE` 0.70, `RISK_REVIEW` 0.45, `NEW_CUSTOMER_REVIEW_USD` 1000 |
| `simulation.py` / `data/risk_tables.json` | risk tables now also carry typical amounts and currency rates (agent-visible reference data, not the hidden truth) |
| `scripts/compare_baseline.py` (new) | runs the engine over all 1,000 transactions and compares with the hidden truth |
| `tests/test_baseline.py` (new) | 33 tests → 89 in total |

## How it was implemented

1. **Eligibility rules (hard constraints, never "probably")** – country, currency, payment method, amount limit, and the provider's **risk tolerance** (`max_risk`). Each rejected provider is reported with its cause (`country_not_supported`, `amount_above_limit`, …).
2. **Cost/risk scoring formula** – expected fee = `amount·fee% + fixed`; estimated approval = `base_rate · uptime · (1 − 0.4·risk)`; provider score = `approval · (1 − fee/amount) − 0.00002·latency_ms` (expected merchant value per attempt, latency only breaks ties).
3. **Decision order (fixed, explainable)** – (1) risk ≥ 0.70 → **decline**; (2) risk ≥ 0.45 → **manual review**; (3) new customer and > 1,000 USD → **manual review**; (4) no eligible provider → **manual review** (never a crash, never a guess); (5) otherwise **route** to the best-scoring eligible provider. Reason codes record every branch; an honest `ONLY_ELIGIBLE_PROVIDER` replaces the misleading "cheapest of one".
4. **Provider constraints** – part of step 2; also cross-checked against `simulation.can_carry` with an assertion so the two definitions cannot drift.
5. **Explanation template only** – the LLM is *not* used yet; the template turns reason codes + numbers into a sentence.
6. **Logging for audit** – one `decision_made` event per decision: transaction id, key inputs, risk score, action, provider, reason codes, eligible list and rejection causes.

## Results on the 1,000 synthetic transactions

| Measure | Value |
|---|---|
| Rank correlation of the baseline risk with the hidden true risk (Spearman) | **0.87** |
| Actions | route 94.4 %, manual review 5.6 %, decline 0 % |
| Fraud rate: routed vs manual review | 1.0 % vs 5.4 % (≈ 5× enrichment) |
| Fraud caught by decline/review | 3 of 12 (25 %) |
| Providers used | alpha_pay 618, epsilon_local_il 145, beta_bank 99, delta_global 82 |
| Average expected fee | 3.2 % of the amount (incl. fixed fees on small payments) |

Honest reading: the ranking is good, but at the default thresholds **no transaction reaches the decline threshold** and only a quarter of the (rare) fraud is stopped. That is a *threshold* question (review at 0.45 is conservative for a 1 % fraud rate), which Day 36–38 will tune with an evaluation set rather than by feel.

**What can rules solve better than LLMs?** Anything with a right answer that must be exact, repeatable and auditable: constraint filtering, fee arithmetic, threshold decisions, reason codes. The 33 tests pin the exact behaviour; the LLM's job (Day 32) is language and second opinions.

## Run & test

```bash
cd Day31
python -m pytest                                   # 89 tests
python -m scripts.compare_baseline                 # 10 decisions + aggregate quality
uvicorn main:app --reload                          # POST /decision/baseline with data/sample_events.json items
```
