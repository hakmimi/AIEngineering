# Day 32 – LLM Reasoning on Top of the Baseline (hybrid decision)

## Goal

Add an LLM **without giving it control**: it explains the rules engine's decision in business language and gives an advisory second opinion, while the final decision stays controlled. Principle: *the LLM may make a decision safer, never riskier.*

```text
Transaction → Baseline Decision → LLM review (explain / agree? / concerns / escalate?) → Control rules → Final Decision
```

## What changed (vs Day 31)

| File | Change |
|---|---|
| `ai_decision.py` (new) | `decide_ai(tx)`: baseline → LLM review → **validation** → **control rules** → final decision; returns baseline, final, review, status, notes, usage, latency |
| `prompts.py` (new) | review prompt (explain, agree?, ≤ 3 concerns, escalate?, confidence) + strict JSON schema; the prompt is fed the transaction, the decision, risk breakdown, top candidates and rejection causes |
| `llm.py` (new) | the single structured-output call (retry, usage tracking, typed errors) |
| `grounding.py` (new) | rejects explanations containing numbers that are not in the data (Month 1's lesson) |
| `usage.py` (reused) | token/cost tracking per decision |
| `schemas.py`, `explanations.py`, `config.py` | new reason code `AI_ESCALATION`; `LLM_MAX_EXPLANATION_CHARS` |
| `main.py` | `POST /decision/ai` |
| `scripts/compare_ai.py` (new) | 10-transaction comparison of baseline vs AI |
| `tests/test_ai_decision.py` (new) | 23 tests → 112 in total |

## How it was implemented

1. **What should the LLM explain?** What was decided, in 2–3 sentences, using only the reason codes, risk components and provider facts it is given.
2. **Where does the LLM enter?** After the baseline, never before: the rules produce the decision of record, the LLM sees it and comments.
3. **Explain, not override** – the prompt says so, **and the code enforces it**: the only power the LLM has is `route → manual_review` when it sets `escalate_to_review` (adds reason code `AI_ESCALATION`, clears provider/cost). It can never approve, change the provider, or soften `manual_review` / `decline` – a test verifies, for every combination of model answers and all three baseline outcomes, that the final action is never more permissive than the baseline.
4. **Structured response contract** – `explanation`, `agrees_with_baseline`, `concerns[]`, `escalate_to_review`, `confidence` under a strict JSON schema; then validated in code: non-empty, ≤ 600 characters, ≤ 3 concerns of ≤ 200 characters, and **no invented numbers** (grounding check against the data the model was shown). An invalid review is discarded (`llm_status="rejected_output"`) and the template explanation is used; it cannot escalate either.
5. **Failure handling** – LLM down/timeouts → `llm_status="unavailable"`, template explanation, decision unchanged.
6. **Context passed** – transaction fields (not the id), decision + reason codes, risk components, top 3 candidates with fee/approval, rejected providers with causes.
7. **Logging** – `decision_made mode=ai baseline_action=… final_action=… llm_status=… agrees=… escalate=… concerns=… changed=… tokens/cost`.

## Live test – 10 transactions (5 sample events + the 5 most borderline routed synthetic payments, risk ≈ 0.43–0.44)

| Result | Value |
|---|---|
| LLM reviews accepted | 10 / 10 (no rejected or unavailable) |
| LLM agreed with the baseline | **10 / 10** |
| Escalation flags / decisions changed | 0 / 0 |
| Average cost / latency added | $0.00045 per decision / ≈ 2.0 s |

Reading: on these cases the LLM adds **readable explanations and concern lists but no challenge value** – it never found a risk the rules missed, even on borderline approvals. That is a finding, not a failure: Day 36–37 will build an evaluation set that includes cases where a second opinion *should* matter, and Day 39 asks whether ≈ 2 s and $0.00045 per decision are worth it for the easy ones (fast path).

## Run & test

```bash
cd Day32
python -m pytest                       # 112 offline tests (LLM mocked)
python -m scripts.compare_ai           # live, ~10 LLM calls
# POST /decision/ai with data/sample_events.json items
```
