# Day 12 – Memory / State

## Goal

Make the system multi-turn: remember what was said in a session so follow-ups like *"And its beaches?"* work, while keeping memory bounded, private per session and observable.

```text
Query → Memory (load history) → rewrite follow-up → Retrieval → LLM (+history) → Response → Memory (save turn)
```

## What changed (vs Day 11)

| File | Change |
|---|---|
| `memory.py` (new) | `MemoryStore`: per-`session_id` history, bounded to the last N turns, LRU eviction across sessions, atomic JSON persistence (`data/sessions.json`), prompt formatter with a character budget, thread lock |
| `chat.py` (new) | `chat(session_id, question)`: load memory → rewrite context-dependent follow-ups (LLM, only when needed) → RAG → save the turn |
| `prompts.py` | `REWRITE_PROMPT`, `CONVERSATION_BLOCK`; `render_rag_prompt(..., history)` injects history *before* the context block |
| `rag.py` | `history` argument threaded through to the prompt |
| `schemas.py`, `routes.py` | `POST /chat`, `GET /session/{id}`, `DELETE /session/{id}`; validated `session_id` (`[A-Za-z0-9_-]{1,64}`) |
| `config.py` | `MEMORY_MAX_TURNS` (6), `MEMORY_MAX_SESSIONS` (500), `MEMORY_PROMPT_CHARS` (1200) |
| `tests/conftest.py`, `tests/test_memory.py` | isolated memory per test; 22 new tests (117 pass) |

## How it was implemented

1. **Session structure** – a session is a list of `{role, content, ts}` messages keyed by `session_id`. State = the conversation only; retrieved chunks and timings are *not* stored (recomputable, would bloat prompts).
2. **What to store / how much** – the last `MEMORY_MAX_TURNS` user+assistant turns per session, and at most `MEMORY_MAX_SESSIONS` sessions (least-recently-used evicted) so memory can't grow without bound.
3. **Persistence** – JSON file written via temp file + `os.replace` (atomic). A corrupt file logs a warning and starts empty rather than crashing.
4. **Inject memory** – `format_for_prompt` takes the newest messages that fit `MEMORY_PROMPT_CHARS`; the block is labelled *"only to understand the question – facts must come from `<context>`"*, so memory cannot become a hallucination source.
5. **Follow-ups** – retrieval on "And its beaches?" would fail (no subject). If history exists *and* the question is short or contains references (it/there/that/…), one LLM call rewrites it to a standalone question; failures fall back to the original. Smalltalk never triggers a rewrite.
6. **Logging** – `chat session=… turns=… rewritten=… history_chars=…`, `memory_write session=… turns=…`, `memory_session_evicted …`; the response carries `session.standalone_question` and `session.used_memory`.

## Live test (one session)

| User says | Retrieval question (rewritten) | Result |
|---|---|---|
| Tell me about Masada | (unchanged) | grounded answer |
| How high is it above the Dead Sea? | How high is the Masada fortress above the Dead Sea? | resolved "it" correctly; safe refusal – the height is not in the data |
| What about Eilat? | What can you tell me about Eilat? | grounded answer |
| And its beaches? | What are the beaches like in Eilat? | resolved "its" → Eilat, grounded answer |
| thanks | – | canned reply, no LLM call |

## Edge cases covered by tests

unknown/new session, bounded history, session isolation, LRU eviction, persistence round-trip, corrupt file, invalid/malicious `session_id` (`../x`, spaces), rewrite failure, prompt budget truncation, delete + re-read.

## Run & test

```bash
cd Day12
python -m pytest tests -q
# POST /chat {"session_id": "demo", "query": "Tell me about Eilat"}   then   {"session_id": "demo", "query": "And its beaches?"}
```

Caveat: memory is per-process file storage; for several workers/servers use Redis or a database (Day 19 moves to SQLite).
