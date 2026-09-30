# Day 19 workflow graph (routing + tools + failure handling + memory)

```mermaid
graph TD;
    START([start]) --> receive_query
    receive_query -. blank .-> END([end])
    receive_query -. no session_id .-> route_query
    receive_query -. session_id .-> load_memory --> contextualize --> route_query
    route_query -. direct .-> direct_answer --> finish
    route_query -. fallback .-> fallback_response --> finish
    route_query -. rag .-> retrieve_context -. ok .-> call_llm -. ok .-> finish
    route_query -. tool .-> select_tool -.-> run_tool -.-> tool_answer -. ok .-> finish
    retrieve_context -. error .-> fallback_node --> finish
    call_llm -. error .-> fallback_node
    finish -. session_id .-> save_memory --> END
    finish -. no session .-> END
```

| Memory node | Reads | Writes |
|---|---|---|
| `load_memory` | store: last turns (budgeted) + long-term facts | `history`, `user_facts`, `memory_used` |
| `contextualize` | `history`, `question` | `standalone_question` (only for context-dependent follow-ups; never for smalltalk) |
| `save_memory` | `question`, `answer`, `source` | stores the turn (not error answers) and extracted facts |
