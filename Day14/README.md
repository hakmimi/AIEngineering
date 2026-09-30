# Day 14 – Project Consolidation

## Goal

Finish the first system: one clean, documented, interview-ready project whose full flow can be explained end to end:

```text
Query → Decision → Retrieval → Memory → Tools → LLM → Response
```

## What changed (vs Day 13)

| Area | Change |
|---|---|
| Structure | Dev/measurement tools moved into `scripts/` (`evaluate`, `retrieval_quality`, `compare_retrieval`, `run_pipeline_demo`), run as `python -m scripts.<name>`; runtime code stays at the top level |
| Cleanup | `ruff --select F` run over the project → one unused import removed |
| Full system | `assistant.py` + `POST /ask`: memory + rule-based tools + RAG in a single entry point |
| Tools | `rule_decision` now also recognises "list the *category* topics" so the common tool cases need **no** decision-LLM call |
| Evaluation | `evaluate.py` can score the complete system (`assistant`) and has a `stability` command |
| Docs | `docs/ARCHITECTURE.md` (flow diagram, module map, decision log with evidence, limits) and this README |
| Tests | `tests/test_assistant.py` – end-to-end flow with mocked LLM (142 tests pass) |

## How it was implemented

1. **Review** – walked the request path top-down and listed each module's job (table in `docs/ARCHITECTURE.md`).
2. **Refactor** – no rewrites; moved measurement scripts out of the runtime folder, fixed imports and usage lines, removed dead imports.
3. **Compose, don't duplicate** – `assistant.ask` only decides *tool or chat*; memory, rewriting, retrieval and prompting are the tested modules from Days 9–13.
4. **Final prompt tuning by evidence** – re-ran the 22-case evaluation against the full system twice:

| Run | Accuracy | Hallucination | False refusal | p50 / p95 latency |
|---|---:|---:|---:|---|
| `v3` (assistant) | 1.00 | 0.00 | 0.00 | 1541 / 2358 ms |
| `v4` (same code, re-run) | 1.00 | 0.00 | 0.00 | – |

   **Stability** (`python -m scripts.evaluate stability v3 v4`): 17/22 answers word-for-word identical, 22/22 with the same pass/fail verdict – wording varies slightly even at temperature 0, correctness did not. No prompt change was needed, so none was made.
5. **Explain it** – the story below.

## The 60-second explanation

> "I built a FastAPI assistant over an Israel knowledge base. Cheap rules decide first: greetings and arithmetic never touch a model. Knowledge questions are embedded, searched in a persisted FAISS index, re-ranked with topic/keyword boosts and expanded with neighbouring chunks. If the best score is too low, the system refuses *before* calling the LLM – that's how hallucination stayed at 0 % on my unanswerable test cases. Follow-ups use per-session memory and an LLM rewrite. I evaluated with a 22-case labelled set (accuracy went 82 % → 100 % after diagnosing sibling-chunk misses), and every component is unit-tested with the LLM mocked."

## Run & test

```bash
cd Day14
pip install -r requirements.txt
python embedding_pipeline.py                 # only if data/embedded_chunks.json is missing
uvicorn main:app --reload                    # POST /ask {"session_id": "me", "query": "Tell me about Eilat"}
python -m pytest tests -q                    # 142 offline tests
python -m scripts.evaluate run mine assistant
```

## Caveats

See "Known limits" in `docs/ARCHITECTURE.md` (small eval set, per-process memory, latency floor of two network calls).
