# Day 11 – Tool Usage

## Goal

Extend the system beyond "LLM + documents": give it **tools** (function-calling mindset) and separate *reasoning* (choosing) from *execution* (running).

```text
Query → Router → Decision (rules | LLM) → Tool  ──► Tool result → LLM phrases answer
                                        └─ search_docs / none → normal RAG
```

## What changed (vs Day 10)

| File | Change |
|---|---|
| `tools.py` (new) | Tool registry with 3 tools – `search_docs`, `calculate`, `list_topics`; Pydantic input models; `ToolResult`; `execute_tool()` that validates, runs, logs and never raises; AST-based `safe_eval` calculator |
| `tool_agent.py` (new) | `rule_decision` (pure arithmetic → no LLM), `llm_decision` (structured output chooses tool + arguments), `run_with_tools` |
| `prompts.py` | `TOOL_CHOICE_PROMPT` (when to use each tool) and `TOOL_ANSWER_PROMPT` (answer only from the tool result) |
| `routes.py` | `POST /ask/tools` |
| `tests/test_tools.py` (new) | 36 offline tests (95 in total) |

## How it was implemented

1. **Tool interface** – `Tool(name, description, input_model, fn)`. Inputs are Pydantic models, so bad arguments are rejected *before* running; outputs are wrapped in `ToolResult(ok, output, error)`.
2. **Who decides tool usage?** A two-level decision layer: cheap deterministic rules first (`12*(3+4)` needs no model to know it is arithmetic), then the LLM with a strict JSON schema whose `tool` field is an enum of the registered tools plus `none`. If the LLM decision fails, the safe default is `search_docs`.
3. **Tool prompting** – the choice prompt describes each tool in one line and tells the model *not* to answer itself and to convert e.g. percentages into an expression – the tool does the math.
4. **Integration** – knowledge questions still go through the Day 9/10 RAG path; `calculate` and `list_topics` execute, then a short prompt phrases the answer from the tool result only. If the phrasing LLM is down, the raw tool result is returned.
5. **Safety** – the calculator parses with `ast` and allows only numbers, `+ - * / % **` and parentheses (no names/calls/attributes); exponents over 100 are rejected.
6. **Logging** – `tool_decision tool=… by=rule|llm|fallback` and `tool_call name=… args=… ok=… error=… ms=…`; the response includes a `tool` object (name, arguments, output, decided_by).

## Live test (8 scenarios)

| Question | Tool (decided by) | Result |
|---|---|---|
| `12*(3+4)` | calculate (rule) | 84 – zero decision-LLM calls |
| What is 15% of 240? | calculate (llm) | 36 |
| List the nature topics | list_topics (llm) | 12 topics |
| Where is Masada? | search_docs → RAG | grounded answer |
| What is the capital of France? | search_docs → RAG | safe refusal |
| What is 10/0? | calculate (rule) | `tool_error`, explained politely |
| hello there friend | – (router) | canned reply, no API call |

## Run & test

```bash
cd Day11
python -m pytest tests -q
# POST /ask/tools {"query": "What is 15% of 240?"}
```
