# Day 22 – Dockerize the System

## Goal

Package the assistant so anyone can run it the same way everywhere: pinned dependencies, a Dockerfile, data that is available (and persistent) inside the container, and documented run commands.

```text
Client → Dockerized FastAPI (uvicorn :8000) → LangGraph workflow → FAISS / tools / LLM → Response
                    └── /app/data  ⇄  ./data on the host (docs, FAISS index, SQLite memory)
```

## What changed (vs Day 21)

| File | Change |
|---|---|
| `requirements.txt` (new) | Runtime dependencies **pinned** to the versions the tests/live runs used; `truststore` only on Windows |
| `requirements-dev.txt` (new) | adds pytest, httpx, ruff |
| `Dockerfile` (new) | `python:3.13-slim`, dependency layer before code (cache), non-root user, writable `/app/data`, `HEALTHCHECK` on `/health`, `uvicorn` on `0.0.0.0:8000` |
| `.dockerignore` (new) | keeps `.env*`, local state (`memory.db`), tests, docs, eval artefacts and caches **out of the image** |
| `docker-compose.yml` (new) | one service, `env_file: .env`, `./data:/app/data` volume, restart policy |

No application code changed.

## Commands

```bash
cd Day22
# .env must contain OPENAI_API_KEY=...   (never committed, never baked into the image)

docker build -t israel-assistant:day22 .
docker run --rm -p 8000:8000 --env-file .env -v "$(pwd)/data:/app/data" israel-assistant:day22
# or:
docker compose up --build

curl http://localhost:8000/health
curl http://localhost:8000/ready
curl -X POST http://localhost:8000/rag/graph -H "Content-Type: application/json" \
     -d '{"query": "Where is Masada?", "session_id": "demo"}'
```

## How it was implemented

1. **requirements.txt / why pin?** `pip freeze`-style pins make builds reproducible: the same versions the 222 tests and live evaluations ran against. Runtime and dev dependencies are split so the image does not ship pytest/ruff.
2. **Dockerfile** – dependencies are installed *before* copying code, so editing code does not re-download packages. Runs as a non-root user; `PYTHONUNBUFFERED=1` makes logs appear immediately in `docker logs`.
3. **What changes inside Docker?** Paths (all derived from `config.BASE_DIR`, so `/app/...` just works), the bind address (`0.0.0.0` – `127.0.0.1` would be unreachable from the host), and secrets (passed at run time via `--env-file`).
4. **Where should data live?** Read-mostly data (docs, embedded chunks, FAISS index) is copied into the image so it runs out of the box; state that must survive rebuilds (SQLite memory, index rebuilds) goes to the mounted `/app/data` volume. If the index file is missing/stale the app rebuilds it from `embedded_chunks.json` (Day 8).
5. **.dockerignore** – the most important line is `.env*`: without it `COPY . .` would bake the API key into an image layer.

## Verification – what was and was NOT done

**Docker is not installed on the machine this was built on, so `docker build`/`docker run` were not executed.** Instead the container was simulated as faithfully as possible:

| Check | Result |
|---|---|
| Build context computed by applying `.dockerignore` to the folder | 34 files, 3.8 MB; **no `.env`**, no tests |
| Fresh virtualenv + `pip install -r requirements.txt` only | all imports succeed (requirements are complete) |
| `uvicorn main:app` run from that context with the key passed as an environment variable (as `--env-file` would) | `/health` 200, `/ready` "ready", `/rag/graph` RAG answer in 3.8 s, tool call `12*(3+4)` = 84, `data/memory.db` created in the writable data dir |

What remains unverified until you run it: the actual image build, the `HEALTHCHECK`, and volume permissions on your Docker host (on Linux, a bind-mounted `./data` must be writable by the container user, uid 1000 – e.g. `chmod -R a+rwX data`).

## Test

```bash
python -m pytest tests -q        # 222 offline tests, unchanged
```
