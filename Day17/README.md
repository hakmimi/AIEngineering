# Day 17 – Tools in the Graph

## Goal

Put **tools inside the workflow** in a controlled way: define tool contracts, add a tool branch to the graph, let the model (or rules) select a tool, validate inputs *and* outputs, and log every execution.

```text
Query → Router ─ tool ─► select_tool ─► run_tool ─► tool_answer (LLM phrases the validated result) ─► Response
                 └ rag ─► retrieve_context ─► call_llm
```

## What changed (vs Day 16)

| File | Change |
|---|---|
| `tools.py` | New tool `calculate_score` (weighted score); every `Tool` now carries an **output validator** (`check_output`) run before the result is used |
| `intent.py` | New route `tool`: rules route obvious arithmetic / "list topics" requests; the LLM classifier can choose it too |
| `graph.py` | New nodes `select_tool`, `run_tool`, `tool_answer`; conditional edge `_after_select`; state keys `tool_name`, `tool_args`, `tool_decided_by`, `tool_result`; response includes a `tool` object |
| `tool_agent.py`, `prompts.py` | LLM tool choice knows `calculate_score` (`numbers`, `weights` fields) |
| `docs/graph.md` | diagram + tool contract table |
| `tests/test_graph_tools.py` | 19 tests (177 pass) |

## How it was implemented

1. **Tools as functions with contracts** – name + Pydantic input model + function + output validator. `search_docs` and `calculate` from Day 11 plus the new `calculate_score`; `list_topics` stays.
2. **What is a tool contract?** Input schema (what may go in), output schema (what may come out) and error behaviour (`ToolResult(ok=False, error=…)`, never an exception).
3. **Where do tools live?** In `tools.py`, outside the graph; nodes only *call* `execute_tool`. That keeps tools unit-testable without LangGraph.
4. **How does the model know which tool to use?** Two-level decision (`select_tool`): rules first (free, exact), else the LLM with a strict JSON schema whose `tool` field is an enum of registered tools + `none`; failure falls back to `search_docs`.
5. **Tool result into state** – `run_tool` stores `{ok, output, error}`; `tool_answer` builds a prompt that says *"answer using ONLY the tool result"*; if the LLM is down, the raw result is returned.
6. **Validation** – inputs by Pydantic + domain checks (length mismatch, negative weights, exponent cap); outputs by `check_output` (finite number, non-empty topic list, well-formed hits). A tool that returns garbage becomes an error *before* the LLM sees it.
7. **Logging** – `graph_tool_selected tool=… by=… args=…`, `tool_call name=… args=… ok=… error=… ms=…`, plus per-node timing.

## Live test

| Question | Mode | Path | Result |
|---|---|---|---|
| `12*(3+4)` | rules | select_tool(rule) → run_tool | 84, "12*(3+4) equals 84." |
| List the history topics | rules | tool `list_topics` | Akko, Archaeology, Caesarea, Masada |
| `10/0` | rules | tool error | `tool_error`, explained politely |
| Where is Masada? | rules | rag | grounded answer (no tool) |
| weighted score of 80, 90, 100 with weights 1, 1, 2 | `LLM_ROUTING=1` | LLM picks `calculate_score` | 92.5 |
| What is 15% of 240? | `LLM_ROUTING=1` | LLM picks `calculate` + builds `0.15*240` | 36 |

Note: in the default rules-only mode natural-language arithmetic ("15% of 240") is *not* recognised and goes to RAG (which refuses) – that is the trade-off Day 16 measured; enable `LLM_ROUTING=1` for it.

## Run & test

```bash
cd Day17
python -m pytest tests -q
# POST /rag/graph {"query": "12*(3+4)"}
```
