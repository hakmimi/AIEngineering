# Day 24 – Token + Cost Tracking

## Goal

Understand and control what a request costs: count input/output tokens from the provider's own usage data, turn them into an estimated cost per request, log it, cap the context size, and measure what each optimisation does to **cost and quality**.

```text
Query → Retrieval → Prompt assembly (token-capped) → LLM → usage recorded → cost logged + returned → Response
```

## What changed (vs Day 23)

| File | Change |
|---|---|
| `usage.py` (new) | `PRICES` (USD / 1M tokens, overridable with `PRICING_JSON`), `estimate_cost()`, `estimate_tokens()`, per-request `UsageTracker` (ContextVar, same pattern as the request id), `record_usage()` |
| `llm.py`, `embeddings.py` | read `response.usage` (`input_tokens`/`output_tokens`; `prompt_tokens` for embeddings) → `llm_usage` / `embedding_usage` log events; a missing usage field never breaks a call |
| `graph.py` | `run_graph` starts a tracker; response gets `usage` (calls, tokens, `estimated_cost_usd`); `graph_done` log carries the same numbers |
| `rag.py` | `build_context` honours `MAX_CONTEXT_TOKENS`: whole chunks, best first, at least one, never cut mid-chunk |
| `config.py` | `MAX_CONTEXT_TOKENS` (default **400**), `JSON_SCHEMA_IN_PROMPT` (default **off**) |
| `scripts/cost_report.py` (new) | runs the 22-case eval under four settings → tokens, cost, accuracy, latency |
| `tests/test_usage_cost.py` (new) | 14 tests (256 pass) |

## How it was implemented

1. **Inspect the response** – the Responses API returns `usage.input_tokens/output_tokens`; embeddings return `usage.prompt_tokens`. We use the provider's numbers (billing truth), not our own estimate.
2. **What drives cost?** Input tokens × price + output tokens × price. Here: the prompt (instructions + context + history) dominates; outputs are ~40 tokens; embeddings cost ≈ nothing ($0.02/1M).
3. **Cost function** – `estimate_cost(model, in, out)`; unknown model → 0 with a warning (tracking must never break a request). Prices are estimates in a table – verify against the provider's current list and override via env.
4. **Per-request roll-up** – a tracker in a ContextVar sums every call made while a request runs (rewrite + tool choice + answer + embedding), so multi-call paths show their true total.
5. **Context guardrail** – `estimate_tokens` (≈ chars/4) budgets the context; whole chunks only, so answers never see half a sentence.

## Measurement: before/after (22-case eval, live, estimated prices)

| Config | Accuracy | Avg LLM input tokens | Avg cost / request | vs baseline |
|---|---:|---:|---:|---:|
| A – baseline (schema repeated in prompt, no cap) | 1.000 | 277.8 | $0.000142 | – |
| B – **schema not repeated in prompt** | 1.000 | 199.7 | $0.000120 | **−15.5 %** |
| C – B + context cap 400 tokens | 1.000 | 199.7 | $0.000119 | −16.2 % |
| D – B + context cap 250 tokens | 1.000 | 192.6 | $0.000115 | −19.0 % |

What we learned
- The biggest **free** saving was not context but *redundancy*: the strict JSON schema is already enforced by the API, so pasting it into every prompt cost ~78 input tokens per call (−28 % input) for nothing.
- Context caps barely mattered **on this data** (documents are 1–3 short chunks; the average context is already small). The cap is kept at 400 tokens as a *worst-case guardrail* for longer documents, not as a measured saving.
- Cost/quality trade-off: quality stayed at 100 % on all four settings, so we take the free savings and stop at 400 rather than squeezing to 250 (less headroom for multi-chunk comparisons, more risk for +3 % savings).
- Absolute scale: ≈ **$0.00012 per LLM request → ≈ $0.12 per 1,000 requests**; free paths (greetings, clarifications, refusals) cost $0. Latency is dominated by the two network round-trips, not tokens.

## Run & test

```bash
cd Day24
python -m pytest tests -q
python -m scripts.cost_report                 # ~90 live requests, cents
# every POST /rag/graph response now has: "usage": {"llm_input_tokens": ..., "estimated_cost_usd": ...}
```

Caveat: prices in `usage.PRICES` are my estimate of list prices at the time of writing – treat costs as relative, and update the table before relying on absolute numbers.
