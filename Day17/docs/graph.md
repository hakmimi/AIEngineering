# Day 17 workflow graph

```mermaid
graph TD;
    START([start]) --> receive_query --> route_query
    receive_query -. blank .-> END([end])
    route_query -. direct .-> direct_answer --> END
    route_query -. fallback .-> fallback_response --> END
    route_query -. rag .-> retrieve_context --> call_llm --> END
    route_query -. tool .-> select_tool
    select_tool -. calculate / calculate_score / list_topics .-> run_tool --> tool_answer --> END
    select_tool -. search_docs / none .-> retrieve_context
```

## Tool contract

| Tool | Input (Pydantic) | Output contract | Rejected when |
|---|---|---|---|
| `search_docs` | `query` 2..1000 chars, `top_k` 1..10 | list of `{topic, text, score}` | bad arguments; malformed hits |
| `calculate` | `expression` ≤ 100 chars | finite number | not arithmetic, `1/0`, exponent > 100, names/calls |
| `calculate_score` | `values` 1..20 numbers, optional `weights` | finite number | length mismatch, negative or all-zero weights |
| `list_topics` | optional `category` | non-empty list of strings | unknown category |

Validation order: **input model → run → output check → (only then) the LLM sees the result.**
