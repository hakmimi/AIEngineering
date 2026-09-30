# Test suite

```bash
pip install -r requirements-dev.txt

python -m pytest                              # everything (~17 s, no network, no API key needed)
python -m pytest -m unit                      # fast, fully isolated
python -m pytest -m api                       # FastAPI endpoints via TestClient
python -m pytest -m integration               # real FAISS/chunking/files over the real documents
python -m pytest --cov=. --cov-report=term    # coverage (config in .coveragerc: scripts/ and tests/ excluded)
python -m pytest tests/test_guardrails.py -k injection
```

| Marker | What is real | What is faked |
|---|---|---|
| `unit` | the function under test | everything else (LLM, embeddings, retrieval, memory store in `tmp_path`) |
| `api` | routing, validation, auth, rate limit, error handlers, middleware | the graph/LLM behind the endpoint |
| `integration` | real documents, chunking, FAISS index, ranking, filters, sibling expansion, index/file handling, embedding pipeline | only the network call (`HashEmbedder`, a deterministic tf-idf hash embedding) |

**Deterministic vs behavioural tests.** Everything here is deterministic. *Behavioural* quality (does the model answer well?) is measured separately by the evaluation scripts, because it needs the real model: `python -m scripts.evaluate`, `scripts.llm_eval`, `scripts.e2e_smoke`.

Shared fixtures live in `conftest.py`: `isolated_memory` (autouse, SQLite in `tmp_path`), `fake_index` / `real_retrieval` (real chunks + fake embeddings), `settings_override` (change the frozen settings, always restored). Add a new file → it is auto-marked `unit` unless listed in the `_API_FILES` / `_INTEGRATION_FILES` sets in `conftest.py`.
