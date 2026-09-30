# Day 19 – Agent Memory / State Persistence

## Goal

Give the graph memory: remember previous turns (**short-term**) and durable facts about the user (**long-term**), persist them across restarts, and use them without letting memory become a source of hallucinated "facts".

```text
Query → Load Memory → Contextualize → Route → Retrieve / Tool → LLM → Save Memory → Response
```

## What changed (vs Day 18)

| File | Change |
|---|---|
| `memory.py` (rewritten) | `BaseMemory` interface; Day 12 JSON store kept; new **`SqliteMemoryStore`** (messages + facts + sessions tables, per-operation connections, transactional writes, LRU eviction incl. facts); `extract_facts()` rules; SQLite is the default `memory` |
| `graph.py` | New nodes `load_memory`, `contextualize`, `save_memory`, join node `finish`; `_q(state)` picks the rewritten question everywhere; state gains `session_id`, `history`, `user_facts`, `standalone_question`, `memory_used`; response gains `session` |
| `prompts.py` | `render_rag_prompt(..., history, facts)`: user-facts and conversation blocks, both labelled "not a fact source" |
| `schemas.py`, `routes.py` | `POST /rag/graph` accepts optional `session_id` (validated); `GET/DELETE /session/{id}` now read the SQLite store |
| `config.py` | `memory_db_path` (`data/memory.db`) |
| `tests/test_graph_memory.py` (new), `tests/conftest.py` | 22 tests; every test gets an isolated SQLite store (213 pass) |

## How it was implemented

1. **What should memory store?** Short-term: the last `MEMORY_MAX_TURNS` user/assistant turns per session. Long-term: durable facts the user states about themselves (`name`, `interest`) – extracted with regex rules (free, predictable, auditable). Not stored: retrieved chunks, timings, and **error answers** (remembering "service unavailable" would poison later turns).
2. **Where does memory enter the flow?** Read *before* routing (`load_memory` → `contextualize`, so routing and retrieval see the standalone question) and written *after* the answer (`save_memory`) on every terminal path – direct answers, tool answers and RAG answers alike. Terminal paths converge on a `finish` node so there is one place to attach saving.
3. **How much memory is useful?** A character budget (`MEMORY_PROMPT_CHARS`) keeps the newest messages that fit; facts are one short line. History goes into the prompt only as context for *understanding the question*.
4. **Why `session_id`?** It is the isolation key: without it there is no memory (the memory nodes are skipped entirely, so the API stays backward compatible) and users cannot see each other's history. Ids are validated (`[A-Za-z0-9_-]{1,64}`).
5. **Persistence** – SQLite: survives restarts, safe for concurrent requests (short-lived connection per operation, transactions), parameterised queries (tested against a SQL-injection payload). JSON store remains for tiny deployments; Redis/Postgres is the multi-server upgrade.
6. **Memory must not break the request** – load/save failures are logged and the request continues without memory (tested with a broken store).
7. **Logging** – `memory_load session=… history_chars=… facts=…`, `memory_rewrite original=… standalone=…`, `memory_write store=sqlite session=… turns=…`, `memory_fact_saved session=… key=…`.

## Live test (one session, real SQLite + OpenAI)

| User says | Retrieval question | Notes |
|---|---|---|
| Hi, my name is Dana. Tell me about Eilat | (unchanged) | fact `name: Dana` saved |
| And its beaches? | What are the beaches like in Eilat? | pronoun resolved; honest refusal – Eilat's text has no beach details |
| What about Masada? | What can you tell me about Masada? | grounded |
| How do visitors reach it? | How do visitors reach Masada? | "it" → Masada from history; answer "cable car or hiking paths" |
| thanks | – | direct reply, no rewrite/LLM; turn saved |

5 turns stored, fact retained, `used_memory` true from turn 2 on.

## Run & test

```bash
cd Day19
python -m pytest tests -q
# POST /rag/graph {"query": "Tell me about Eilat", "session_id": "me"}   then   {"query": "And its beaches?", "session_id": "me"}
# GET /session/me     DELETE /session/me
```
