# Day 33 – Tools for the Decision Agent

## Goal

Make the agent **use functions instead of relying on prompt context**: exact lookups (risk, eligible providers, cost) run as validated, logged tool calls, and the LLM's explanation is grounded in what those tools returned.

```text
Transaction → Tool calls (risk_lookup → provider_lookup → cost_estimate…) → Baseline rules → LLM explanation → Response (+ tool trace)
```

## What changed (vs Day 32)

| File | Change |
|---|---|
| `tools.py` (new) | three tools with **Pydantic input models**, **output contracts**, `execute_tool()` (validate → run → validate output → log → trace; never raises) and a `ToolTrace` |
| `tool_pipeline.py` (new) | `ToolGatherer` + `decide_with_tools(tx)`: the *same* baseline rules, but data is fetched through tools; a failing tool becomes a `manual_review` with reason `TOOL_ERROR` |
| `decision_engine.py` | data access extracted into a `DirectGatherer`; `decide_baseline(tx, gatherer=None)` – rules unchanged |
| `prompts.py`, `ai_decision.py` | the review prompt now contains **"Tool results"**; the grounding check accepts numbers from tool outputs; the AI result and API include `tool_trace` |
| `grounding.py` | numbers may be exact, a percentage form, or **ordinarily rounded** ("92 %" for 0.9235) – invented values are still rejected |
| `main.py` | `POST /decision/tools` (rules over tools, no LLM, returns the trace) |
| `schemas.py`, `explanations.py` | reason code `TOOL_ERROR` |
| `tests/test_tools.py` (new) | 24 tests (+1 grounding test) → 138 in total |

## How it was implemented

1. **What should be a tool?** Anything with an exact answer that could change independently of the prompt: risk lookup (tables + arithmetic), provider eligibility (hard constraints), cost/approval estimate (arithmetic). Ranking and the action remain the rules engine's job.
2. **Why compute cost outside the LLM?** LLMs approximate arithmetic; a fee that is 4.2 must never become 4.3. Tools compute, the LLM narrates.
3. **Tool interface** – `name`, `description`, Pydantic `input_model`, function, `check_output`. Bad arguments fail before running (`invalid arguments: merchant_category…`); garbage outputs (risk 7.0, overlapping provider lists) are rejected *before* any decision uses them.
4. **Connecting tools to data** – tools call the loaders (`data_loader`) and the same risk/eligibility/score functions, so there is one definition of each rule.
5. **Tools in the pipeline** – `risk_lookup` first; if the risk rules already decide (decline/review) no provider tool is called; otherwise `provider_lookup`, then one `cost_estimate` per eligible provider.
6. **Prompt** – the trace (tool, arguments, result) is embedded and the model is told to base its explanation on it; grounding is checked against the same text.
7. **Logging** – `tool_call tool=… args=… ok=… error=… output=… ms=…` per call; `decision_made … tool_calls=N`; the API returns the full trace.

## The key test

`decide_with_tools(tx) == decide_baseline(tx)` – decision, rejected providers and candidate order – for **300 transactions**. Fetching data through tools must not change a single decision; it passes.

Failure handling (tested for each tool): a broken `risk_lookup`, `provider_lookup` or `cost_estimate` yields `manual_review` + `TOOL_ERROR` (risk assumed 0.5) with the failure reported in `notes`/`tool_failure` – never a 500.

## Live result (same 10 transactions as Day 32)

| | Day 32 (data in prompt) | Day 33 (tool trace in prompt) |
|---|---|---|
| LLM reviews accepted / agreed | 10 / 10 · 10 / 10 | 10 / 10 · 10 / 10 |
| Avg cost per decision | $0.000445 | **$0.000608 (+37 %)** |
| Avg latency | 2.0 s | 2.05 s |

The trace makes the explanation auditable ("which lookups did it rest on?") but costs ≈ 37 % more input tokens; Day 39 weighs that against skipping the LLM for easy cases.

## Run & test

```bash
cd Day33
python -m pytest                    # 138 offline tests
python -m scripts.compare_ai        # live
# POST /decision/tools   -> decision + tool_trace (no LLM)
# POST /decision/ai      -> decision + LLM review + tool_trace
```
