# Day 34 – The Decision Workflow as a LangGraph Graph

## Goal

Turn the decision pipeline into an explicit **stateful graph**: routing, tools, baseline rules and the LLM become named nodes with shared state, so the flow is inspectable, timed per node and ready for Day 35's branching and fallbacks.

```text
Transaction → LangGraph State → Tool Nodes → Baseline Node → LLM Node → Finalize → Response
```

## What changed (vs Day 33)

| File | Change |
|---|---|
| `decision_graph.py` (new) | `DecisionState`, nine nodes, four conditional edges, `run_decision_graph(tx)`; per-node timing and trace with reducers |
| `decision_engine.py` | `decide_baseline` split into reusable rule sets: `risk_rule_decision` (decline/review) and `select_provider` (rank + choose) – behaviour unchanged, so graph nodes call the *same* rules |
| `ai_decision.py` | `validate_review` and `apply_control_rules` made public (the graph reuses them); result carries `graph_trace` / `graph_timings` |
| `main.py` | `POST /decision` runs the graph and returns decision, LLM review, tool trace, node trace and per-node timings |
| `scripts/draw_graph.py`, `docs/graph.md` (new) | Mermaid diagram generated from the compiled graph |
| `tests/test_graph.py` (new) | 16 tests → 154 in total |

## The graph

```text
input → risk_tool → rules ──(risk rules decided: decline / review)──────────────┐
                      └──(needs a provider)→ provider_tool → cost_tool → select ─┤
                                                                                 ▼
any tool failure → tool_error ───────────────────────────────────────→ llm_explain → finalize → END
```
Generated diagram: [`docs/graph.md`](docs/graph.md).

| Node | Does | Reads → writes (state) |
|---|---|---|
| `input` | initialise run objects (the API model already validated the input) | → `tool_trace` |
| `risk_tool` | `risk_lookup` tool | `transaction` → `risk` (or `error`) |
| `rules` | risk rules: decline / manual review | `risk` → `baseline` (only if decided) |
| `provider_tool` | `provider_lookup` tool | → `candidates` (ids), `rejected` |
| `cost_tool` | one `cost_estimate` call per eligible provider | → priced `candidates` |
| `select` | rank and choose (baseline decision node) | → `baseline` |
| `llm_explain` | LLM review, validated and grounded | → `review`, `llm_status`, `notes` |
| `tool_error` | a lookup failed → manual review with `TOOL_ERROR`, no LLM call | `error` → `baseline` |
| `finalize` | control rules (LLM may only escalate route → manual review) | → `decision` |

## How it was implemented

1. **What should the graph remember?** The transaction, risk assessment, candidates and rejections, the baseline decision, the LLM review + status, notes, the final decision, the tool trace, and (via reducers) the ordered node `trace` and merged `timings`.
2. **What belongs in a node?** One step with a clear input/output and failure mode. Business rules stay in `decision_engine` and data access in `tools`; nodes are thin adapters, which is why the graph reuses the exact same rules as the non-graph code.
3. **How do tools connect?** Provider and cost tools are separate nodes so each lookup is timed and can fail on its own; every call is traced.
4. **LLM node responsibility** – produce a *reviewed explanation* only; validation (length, grounding) happens in the node, decision changes happen in `finalize` under the control rules.
5. **Where does graph execution start?** FastAPI validates the body with the `Transaction` model and calls `run_decision_graph`; orchestration lives entirely in the graph.
6. **Conditional edges** read state only: after `rules` skip the provider nodes when risk already decided; after each tool node go to `tool_error` on failure.

## Verification

- **Equivalence (the important test):** for 200 synthetic transactions the graph's baseline decision equals `decide_baseline` and its final decision equals `decide_ai` (LLM mocked identically).
- Each path has an exact-trace test: routed, decline, review, no eligible provider, and a failing `risk_lookup` / `provider_lookup` / `cost_estimate` (each ends in `tool_error → finalize`, no LLM call, `TOOL_ERROR`).
- Live on the 5 sample events: routed events take 8 nodes, review/decline take 5; LLM node ≈ 2.0–3.0 s of the total, every tool node < 1 ms – **the LLM is the latency**.

## Run & test

```bash
cd Day34
python -m pytest                          # 154 offline tests
python -m scripts.draw_graph              # regenerate docs/graph.md
# POST /decision   (the graph)
```
