# Day 28 – Final Portfolio Packaging (Month 1 deliverable)

[![CI](https://github.com/hakmimi/AIEngineering/actions/workflows/ci.yml/badge.svg)](https://github.com/hakmimi/AIEngineering/actions/workflows/ci.yml)

**Israel Knowledge Assistant** – a FastAPI + LangGraph RAG service with guardrails, tools, memory, observability and an evaluation harness.

```text
Client → API → Guardrails → Graph Router → Memory / Retrieval / Tools → LLM → Output Guard → Logs + Cost → Response
```

## Goal

Finish Month 1 as a **portfolio case study**: verify everything runs end to end, make the documentation good enough for a reviewer, explain the design and its trade-offs honestly, present the evaluation evidence, prepare the interview story, and list what Month 2 must improve.

## What changed (vs Day 27)

No application code changed – this day is verification and communication.

| Deliverable | Where |
|---|---|
| Architecture: request flow, layers, design decisions **with the measurement behind each**, known limits | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Workflow diagram, regenerated from the compiled graph (now includes guardrails) | [`docs/graph.md`](docs/graph.md) |
| 2-minute explanation, likely interview questions with answers, 5 CV bullets | [`docs/INTERVIEW.md`](docs/INTERVIEW.md) |
| Month 2 improvement backlog tied to evidence | [`docs/BACKLOG.md`](docs/BACKLOG.md) |
| Final evaluation section (below) | this README |

## How it was verified (steps 1–4)

| Step | Result |
|---|---|
| Run the "Dockerized" app end to end | Docker is not installed here, so the container was simulated on Day 22 (clean venv, image-like context, key via env). Not re-run as a real container. |
| Full tests locally | **400 passed**, `ruff` clean, coverage 99 % |
| CI status | workflow exists and its exact steps were run in a clean venv on Day 27 (400 passed, 99.21 %); **not yet observed on GitHub** (nothing pushed) |
| Live end-to-end smoke (`scripts.e2e_smoke`) | **12 / 12** scenarios through the real API: greeting, clarify, fact, comparison, refusal, both tools, 3-turn memory with follow-up + fact recall, 2 validation cases |
| Logs from sample requests (`scripts.log_demo`, Day 23) | one JSON line per event, all tied by `request_id`; bottleneck is the embedding/LLM network call, not FAISS |

## Final evaluation results (live, this day)

| Evaluation | Result |
|---|---|
| LLM judge, 36 cases (relevance / accuracy / groundedness) | pass rate **1.00**, all three scores 5.0 (keyword cross-check agrees on 97 %) |
| Keyword eval, 22 cases through the full graph | accuracy 1.00 · hallucination 0.00 · false refusal 0.00 · retrieval hit 1.00 · p50 1.4 s · p95 2.0 s |
| Guardrails (46 inputs) | 23/23 in-scope attacks blocked, **0/19** legitimate inputs blocked; 4 documented gaps (paraphrase, obfuscation, indirect extraction, Hebrew) |
| Cost (22 cases) | ≈ $0.00012 per LLM request; −16 % from removing a redundant schema from prompts, quality unchanged |

How the numbers improved along the way: retrieval precision 0.43 → 0.91 (Day 9), eval accuracy 82 % → 100 % (Day 13, sibling-chunk expansion), judged pass rate 0.97 → 1.00 (Day 25, prompt-extraction now blocked), tests 41 → 400.

## Trade-offs (details and evidence in `docs/ARCHITECTURE.md`)

Rules first, LLM optional · refuse before generating · one retry layer · narrow guardrails (false positives cost real users) · SQLite over Redis · simple prompt over a stricter one that measured no better.

## Honest limits

Small, clean, English data (77 chunks); 100 % on 22–36 cases is easy and cannot rank strong systems; guardrails are rule-based; Docker/CI validated by simulation only; single-node memory and rate limiting; prices are estimates. The full list is in `docs/ARCHITECTURE.md` and the backlog in `docs/BACKLOG.md`.

## Month 2 backlog (top items)

1. Decision-agent project with the eval set **built first** (Days 29–56).
2. Bigger/adversarial eval with held-out split and a different judge model.
3. Real Docker build + first GitHub Actions run.
4. Learned guardrail layer behind the rules; hybrid BM25 + dense retrieval.

## Run

```bash
cd Day28
cp .env.example .env                       # set OPENAI_API_KEY
pip install -r requirements.txt
uvicorn main:app --reload                  # POST /rag/graph {"query": "Where is Masada?", "session_id": "me"}
python -m pytest --cov=. --cov-fail-under=95
python -m scripts.e2e_smoke                # live, needs the key
docker compose up --build                  # see Day 22 notes: not verified on this machine
```
