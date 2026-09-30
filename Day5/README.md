# Day 5 – RAG Reliability + Error Handling

The original lesson plan (objectives, layer table, tips) is kept in [PLAN.md](PLAN.md).

## Goal

Move the Day 4 RAG service from **"prototype that works on good inputs"** to **"production-minded"**:
it must stay stable and honest on empty input, irrelevant questions, noisy data and LLM outages.

```text
Query → Retrieve → Filter/Rank → Validate → Inject Context → LLM → Fallback (if needed) → Response
```

## What changed

| Area | Before (Day 4) | After (Day 5) |
|---|---|---|
| Data (`chunk.py`, `embedding_pipeline.py`) | Raw split every 30 words; script ran on import | `clean_text()` (unicode, HTML tags, control chars, whitespace); tiny tail chunks and duplicate chunks dropped; pipeline behind `__main__` |
| Retrieval (`retrieval.py`) | Top-k by cosine only, irrelevant chunks still returned | Score = cosine + small keyword-overlap boost; chunks under `MIN_CHUNK_SCORE` removed; results carry both `similarity` and `score` |
| Validation (`rag.py`) | LLM always called (fell back to ungrounded LLM answer) | `validate_context()` blocks the LLM call when there is no context or best score < `RETRIEVAL_THRESHOLD`; returns a safe "not enough information" answer |
| Prompt (`rag.py`) | Short "use only the context" prompt | Numbered rules: context-only, exact refusal sentence, max 3 sentences, cite `[doc_id chunk_id]`, ignore instructions inside context, lower confidence when partial |
| Error handling (`llm.py`, `rag.py`) | LLM errors bubbled up as 503 | `llm.get_answer` maps any `OpenAIError` (timeout, rate limit, connection) to `ExternalServiceError`; `get_rag_answer` catches it and returns a fallback answer (`source: fallback_error`) |
| Timeout | – | Client-level `OPENAI_TIMEOUT_SECONDS` (20s) + `OPENAI_MAX_RETRIES` (2), enforced by the OpenAI SDK |
| Logging | Free-form messages | One `key=value` line per decision: `retrieval …`, `decision=rag / blocked_no_context / fallback_llm_unavailable`, `app_error …`, `unexpected_error …` |
| API (`main.py`) | Global exception handlers only in Day 4 | Same handlers, fixed routes; `/rag` response always has `source` ∈ `rag`, `no_context`, `invalid_input`, `fallback_error` |

New config knobs in `config.py`: `MIN_CHUNK_WORDS`, `MIN_CHUNK_SCORE`, `KEYWORD_BOOST`, `MIN_CONTEXT_CHUNKS`.

## How it was implemented

1. **Chunk quality** – `chunk.clean_text` normalises text before splitting; `chunk_text` discards chunks shorter than `MIN_CHUNK_WORDS`. `embedding_pipeline.build_embedded_chunks` skips exact-duplicate chunks.
2. **Ranking** – `retrieval.score_chunk = cosine + KEYWORD_BOOST × keyword_overlap(query, chunk)`. Overlap is the fraction of non-stopword query terms found in the chunk. Simple on purpose (plan: *"Overcomplicating ranking"* is an anti-pattern).
3. **Filtering** – `retrieval.filter_chunks` applies the minimum score after taking top-k, so weak matches never reach the prompt.
4. **Validation gate** – `rag.validate_context` is the single place that decides "may we call the LLM?". Blank question → `invalid_input` (no embedding cost either).
5. **Prompt** – `RAG_PROMPT` template in `rag.py`; the refusal text is shared with the code (`NO_CONTEXT_ANSWER`) so behaviour is identical whether the gate or the model refuses.
6. **Failure isolation** – provider errors are converted at the boundary (`llm.py`, `embeddings.py`) into `AppError` subclasses; `rag.py` decides the user-facing fallback.
7. **Bug fixes while porting the Day 4 code** – `json.loaf` typo, missing `@` on route decorators, `logging.basicConfig(level=logging.info)`, `%(actime)s`, `return` inside the retrieval loop, and endpoints returning the string `'response'`.
8. **Side fix** – an IDE auto-import had rewritten `from config import settings` to `from Day5.config import …` in `Day4ProductionUpgrade/*.py`; restored.

## Run & test

```bash
cd Day5
python embedding_pipeline.py        # builds data/embedded_chunks.json (needs OPENAI_API_KEY)
uvicorn main:app --reload
python -m pytest tests -q           # 16 offline tests, no API calls
```

Edge cases covered by `tests/test_reliability.py`: empty/blank query, invalid `top_k`, missing body, low-quality retrieval (`Lumaria`, `Port Azure` style questions), LLM failure, unexpected exception, noisy text, tiny chunks.

## Status / caveats

- Unit tests pass (16/16). A **live end-to-end run was not possible in this environment** (`SSL: CERTIFICATE_VERIFY_FAILED` when reaching OpenAI), so `data/embedded_chunks.json` is not generated yet – run the pipeline locally first.
- Thresholds (`RETRIEVAL_THRESHOLD=0.55`, `MIN_CHUNK_SCORE=0.30`) are starting values; tune them against real scores (Day 9 covers retrieval quality).
