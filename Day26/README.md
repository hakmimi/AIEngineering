# Day 26 – Tests

## Goal

Make the project safe to change: a test suite that covers the API, routing, retrieval, guardrails and failure paths **without a network or API key**, with mocked LLM/embedding calls, clear categories, a coverage number, and documented commands.

```text
Code change → pytest (unit + api + integration) → coverage → confidence
```

## What changed (vs Day 25)

| File | Change |
|---|---|
| `pytest.ini` (new) | `testpaths`, markers `unit` / `api` / `integration`, warning filter |
| `.coveragerc` (new) | coverage of application code only (`scripts/`, `tests/` excluded) |
| `tests/conftest.py` | shared fixtures (`fake_index`, `real_retrieval`, `settings_override`) and automatic marker assignment |
| `tests/fakes.py` (new) | `HashEmbedder` – deterministic tf-idf hash embeddings; builds a real FAISS index from the **real** documents |
| `tests/test_retrieval_relevance.py` (new, 23 tests) | real chunking + FAISS + ranking + filters + sibling expansion; defines "relevant enough" operationally |
| `tests/test_api.py` (new, 32 tests) | validation (8 invalid payloads), auth on every protected endpoint, rate limit incl. window expiry, error shapes (no leaked internals), OpenAPI surface, tracing headers |
| `tests/test_llm_and_data_paths.py` (new, 23 tests) | provider error classification (retryable vs not), non-JSON model output, missing key, corrupt/missing data files, FAISS build/load/rebuild-when-stale, embedding pipeline (cleaning, dedupe, metadata, topic prefix) |
| `tests/README.md` (new) | how to run, what each marker means |

Existing tests from Days 8–25 are kept and now tagged with markers.

## Result

| | |
|---|---|
| Tests | **392 pass** (was 314), ≈ 17 s, offline |
| Coverage of application code | **99 %** (1,521 statements, 12 missed – e.g. the optional `truststore` import fallback) |
| By marker | 295 unit · 44 api · 53 integration |
| Isolation | every test file passes when run alone; no test touches `data/memory.db` |

Before this day, coverage was 87 % *including* scripts; the real gaps were security (auth, rate limit), the retrieval data-loading errors, the LLM error paths, the FAISS files and the embedding pipeline – exactly what this day's tests target.

## How it was implemented / answers to the day's questions

- **What should be unit tested?** Pure decisions and contracts: routing, guardrails, tool validation, prompt/context building, scoring, memory rules, error classification.
- **What is "relevant enough"?** For a query that shares words with a topic, that topic must be ranked first (12 cases, ≥ 90 % required; all pass); for a query sharing no words with anything, nothing may be returned; a category/topic filter must never leak other categories. This runs on the *real* 77 chunks with only the embedding call faked.
- **Do bad inputs fail safely?** Guardrail tests (Day 25) + 8 malformed payloads → 422, unknown route → 404, wrong method → 405, unexpected exception → 500 with a request id and **no internal message**.
- **Why mock external APIs?** Speed (17 s vs minutes), determinism (LLM output varies even at temperature 0 – measured on Day 14), cost, and the ability to inject failures (429, timeouts, invalid JSON, corrupt files) that are hard to produce for real.
- **Fallback behaviour** – Day 18's failure-injection tests plus this day's provider-error classification.
- **Deterministic embedder design** – 32,768 dimensions on purpose: a first version with 2,048 dimensions produced hash collisions that made unrelated queries look slightly similar to real chunks; the test for "unrelated queries return nothing" caught it.

## Run

```bash
cd Day26
pip install -r requirements-dev.txt
python -m pytest                     # or: -m unit | -m api | -m integration
python -m pytest --cov=. --cov-report=term
```
