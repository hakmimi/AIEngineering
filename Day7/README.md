# Day 7 – Refactor + Clean Architecture

## Goal

Same behaviour as Day 6, easier to read and explain ("If you can't explain it, you don't understand it"):

- one responsibility per module
- no duplicated code
- prompts standardised in one place
- a pipeline that reads top to bottom
- *avoid over-refactoring* – no new framework, no behaviour change

## What changed (vs Day 6)

| Before | After |
|---|---|
| OpenAI client built twice (`llm.py`, `embeddings.py`) | `openai_client.get_client()` – one lazy shared client, one missing-key check |
| Prompt text, refusal sentence and JSON suffix scattered across `rag.py` / `llm.py` | `prompts.py` – `RAG_PROMPT`, `NO_CONTEXT_ANSWER`, `LLM_DOWN_ANSWER`, `render_rag_prompt()`, `with_json_schema()` |
| `main.py` held app setup, schema and every endpoint | `main.py` = wiring (middleware, error handlers); `routes.py` = endpoints; `schemas.py` = `SearchRequest` |
| `get_rag_answer` was one 30-line function with several early returns | Three small functions: `_answer_directly`, `_answer_from_context`, and a 6-line `get_rag_answer` that just routes |
| `_response(...)` private helper | `build_response(...)` – the single place that shapes the result and logs it |
| `llm.get_answer` mixed the API call and parsing | `_call_model` (network) + `get_answer` (parsing) |
| Import-time client creation (`client = None` checks) | Client created on first use, so importing modules never needs a key |

No behaviour changes: routes, response fields, thresholds and logs are identical to Day 6.

## How it was implemented

1. **Split modules** – moved code, didn't rewrite it. Dependency direction is one-way: `routes → rag → (router, retrieval, llm, prompts, timing)`; `llm`/`embeddings → openai_client`.
2. **De-duplicate** – client creation and the "API key not configured" check now exist once.
3. **Standardise prompts** – every string the user or model sees is in `prompts.py`. `rag.py` re-exports the names so existing imports/tests keep working.
4. **Simplify pipeline** – early-return branches became named functions, so `get_rag_answer` reads: time the routing → skip route? answer directly → otherwise answer from context.
5. **Comments** – module docstrings state each file's single job; inline comments explain *why*, not *what*.
6. **Safety net** – the Day 5 + Day 6 test suites ran unchanged (two mock targets updated for the moved code), plus one new test for the missing-key path.

## Module map

```text
main.py            app wiring: middleware, error handlers
routes.py          HTTP endpoints only
schemas.py         request models
rag.py             pipeline: route → retrieve → validate → prompt → LLM
router.py          rule-based decision layer
retrieval.py       load chunks, score, filter
prompts.py         all prompts + fixed answers
llm.py / embeddings.py / openai_client.py   provider access
timing.py, security.py, config.py, errors.py, chunk.py, similarity.py, embedding_pipeline.py
```

## Run & test

```bash
cd Day7
python embedding_pipeline.py     # once, needs OPENAI_API_KEY
uvicorn main:app --reload
python -m pytest tests -q        # 34 offline tests
```

## Caveat

Not run against the live OpenAI API (SSL certificate error in the build environment) – refactor is verified by the offline tests only.
