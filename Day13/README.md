# Day 13 – Evaluation System

## Goal

Stop guessing: **measure** quality with a repeatable evaluation, find weaknesses from data, fix them, and prove the improvement.

```text
Eval set → System → Scoring → Results (JSON + CSV) → Weaknesses → Fix → Re-run → Compare
```

## What changed (vs Day 12)

| File | Change |
|---|---|
| `data/eval/eval_set.json` (new) | 22 labelled cases: 11 facts, 2 comparisons, 2 fictional-but-in-KB, 3 out-of-domain, 2 unanswerable-in-domain (right topic, fact absent), 1 adversarial |
| `evaluate.py` (new) | `run <label> [rag\|multistep]`, `compare <a> <b>`; per-case scoring, aggregate metrics, JSON + CSV output |
| `retrieval.py` | **Fix from evaluation:** `expand_with_siblings()` and a `wide` margin for complex questions |
| `config.py` | `EXPAND_SIBLINGS`, `MAX_CONTEXT_CHUNKS`, `COMPLEX_SCORE_MARGIN` |
| `rag.py` | complex routes use the wide margin |
| `tests/test_evaluation.py` (new) | 13 tests for scoring, eval-set validity, sibling expansion (130 pass) |

## Evaluation criteria (what "quality" means here)

| Metric | Definition |
|---|---|
| `accuracy` | share of cases passed |
| `retrieval_hit_rate` | the expected topic(s) were retrieved (`any`, or `all` for comparisons) |
| `avg_keyword_score` | share of required fact groups found in the answer (each group is any-of) |
| `hallucination_rate` | unanswerable questions that were **answered** instead of refused |
| `false_refusal_rate` | answerable questions that were refused |
| latency p50 / p95 | end-to-end per question |

Scoring is deterministic (keywords + refusal detection). An LLM judge for relevance/groundedness comes on Day 20.

## How it was implemented / the improvement loop

1. **Criteria + sample queries** – cases written from the documents, including traps: questions whose topic exists but whose fact does not ("population of Tel Aviv"), and a prompt-injection style request.
2. **Run** – `python evaluate.py run v1` → `results_v1.json/.csv`, failures printed with retrieved topics and the answer.
3. **Weaknesses found (v1: 82 % accuracy, comparisons 0 %)**
   - *"Which UNESCO site is in Haifa?"*, *"How do visitors reach Masada?"* → right topic retrieved, but the model said "context does not provide…": the answer sentence sat in a **sibling chunk** that the adaptive top-k had cut.
   - *Both comparison questions* → only one side retrieved (relative cutoff too strict for multi-entity questions).
4. **Fixes** – (a) neighbour expansion: add the other chunks of each retrieved document (grouped per document, capped at 8, flagged `expanded`); (b) `wide` margin (0.30 instead of 0.12) for complex/comparison routes.
5. **Re-test** – `python evaluate.py run v2` and `compare`.

## Results

| Metric | v1 | v2 | Δ |
|---|---:|---:|---:|
| accuracy | 0.818 | **1.000** | +0.182 |
| comparison accuracy | 0.00 | 1.00 | +1.00 |
| retrieval hit rate | 0.944 | 1.000 | +0.056 |
| false refusal rate | 0.125 | 0.000 | −0.125 |
| hallucination rate | 0.000 | 0.000 | 0 |
| latency p50 / p95 | 1356 / 2170 ms | 1481 / 1852 ms | ≈ same |

## Caveats – read before trusting the 100 %

- 22 cases is a **small** set and it was used to find *and* verify the fixes, so it can over-state generalisation. The fixes are general mechanisms (not case-specific hacks), but Day 20 adds a bigger set and a judge, and a held-out split would be the next step.
- Keyword matching can miss correct paraphrases and reward keyword-stuffing; hence the LLM judge later.

## Run & test

```bash
cd Day13
python evaluate.py run v3            # costs ~ 22 short LLM calls
python evaluate.py compare v1 v2
python -m pytest tests -q            # offline
```
